from functools import lru_cache
from langchain import hub
from langchain_core.documents import Document
from langgraph.graph import START, StateGraph
from typing_extensions import List, TypedDict
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain.chat_models import init_chat_model
from langchain_community.vectorstores import FAISS
import getpass
import os
from dotenv import load_dotenv
import mlflow
import time
from langfair.auto import AutoEval
import asyncio
# Load the FAISS index
from google.cloud.storage import Client
import tempfile
import os
load_dotenv(override=True)
mlflow.langchain.autolog()
MLFLOW_TRACKING_URI =os.environ.get("MLFLOW_TRACKING_URI")
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
FAISS_INDEX_FOLDER= os.getenv('FAISS_INDEX_FOLDER')
mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)  # Remote MLflow Server
mlflow.set_experiment("rag_experiment")
if not os.environ.get("MISTRAL_API_KEY"):
  os.environ["MISTRAL_API_KEY"] = getpass.getpass("Enter API key for Mistral AI: ")

@lru_cache(maxsize=None)
def get_llm():
    llm = init_chat_model("mistral-large-latest", model_provider="mistralai")
    return llm

@lru_cache(maxsize=None)
def get_prompt():
# Define prompt for question-answering
    prompt = hub.pull("rlm/rag-prompt")
    return prompt


# Define state for application
class State(TypedDict):
    question: str
    context: List[Document]
    answer: str


@lru_cache(maxsize=None)
def load_embeddings():
    embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
    return embeddings



# Initialize GCS client
storage_client = Client()
bucket=storage_client.bucket(os.getenv('BUCKET_NAME'))
embeddings=load_embeddings()
if not os.path.exists(FAISS_INDEX_FOLDER):
    os.makedirs(FAISS_INDEX_FOLDER, exist_ok=True)
# Create a temporary directory
# Download FAISS index files from bucket to FAISS_INDEX_FOLDER directory
for blob in bucket.list_blobs(prefix=FAISS_INDEX_FOLDER):
    # Extract just the filename from the full path
    filename = os.path.basename(blob.name)
    local_path = os.path.join(FAISS_INDEX_FOLDER, filename)
    blob.download_to_filename(local_path)

# Load FAISS index from directory
vector_store = FAISS.load_local(FAISS_INDEX_FOLDER, embeddings, allow_dangerous_deserialization=True)
# Define application steps
def retrieve(state: State):
    with mlflow.start_run(nested=True, run_name="retrieval"):
        start_time = time.time()
        retrieved_docs = vector_store.similarity_search(state["question"])
        retrieval_time = time.time() - start_time
    
        # Extract only metadata
        doc_metadata = [{"doc_id": doc.metadata.get("id", i), "source": doc.metadata.get("source", "unknown")}
                        for i, doc in enumerate(retrieved_docs)]
        
        # Log metadata instead of full documents
        mlflow.log_metric("retrieval_time", retrieval_time)
        mlflow.log_param("retrieved_docs_count", len(retrieved_docs))
        mlflow.log_dict(doc_metadata, "retrieved_docs.json")

    return {"context": retrieved_docs}

# Initialize LLM once and store in a global variable
llm = get_llm()
# Initialize prompt once and store in a global variable
prompt = get_prompt()
def generate(state: State):
    with mlflow.start_run(nested=True, run_name="generation"):
        start_time = time.time()
        docs_content = "\n\n".join(doc.page_content for doc in state["context"])
        token_count = len(docs_content.split()) 
        # Use the global prompt instance
        mlflow.log_param("retrieved_tokens", token_count)
        mlflow.log_param("context_length", len(docs_content))
        messages = prompt.invoke({"question": state["question"], "context": docs_content})
        response = llm.invoke(messages)
        generation_time = time.time() - start_time
        
        # Log LLM generation performance
        mlflow.log_metric("generation_time", generation_time)
        mlflow.log_param("response_length", len(response.content.split()))
        mlflow.log_param("model_name", "mistral-large-latest")

        # Save response
        # with open("response.txt", "w") as f:
        #     f.write(response.content)
        # mlflow.log_artifact("response.txt")

    return {"answer": response.content}


def generateResponse(query):
# Compile application and test
    try:
         with mlflow.start_run(run_name="RAG_Pipeline"):
            mlflow.log_param("query", query)
            graph_builder = StateGraph(State).add_sequence([retrieve, generate])
            graph_builder.add_edge(START, "retrieve")
            graph = graph_builder.compile()
            response = graph.invoke({"question": f"{query}"})
            mlflow.log_param("final_answer", response["answer"])
            return response["answer"]
    except Exception as e:
        mlflow.log_param("error", str(e))
        raise Exception(e)
    
async def checkModel_fairness():
    auto_object = AutoEval(
        prompts=["tell me about khoury"], 
        langchain_llm=llm,
        # toxicity_device=device # uncomment if GPU is available
    )
    results = await auto_object.evaluate()
    print(results['metrics'])
    
if __name__ == "__main__":

    query=input("generate query")
    response=generateResponse(query)
    print(response)
    #uncomment and enter prompts for model fairness and there is a limitation on api key
    # asyncio.run(checkModel_fairness())