import streamlit as st
import requests
from dotenv import load_dotenv
import os
load_dotenv(override=True)
# Define the backend API URL
API_URL = os.getenv('API_URL')  # Update if running on a different host

st.title("NuBot Chat Interface")
st.markdown("### Ask NuBot any question!")

# User input
query = st.text_input("Enter your query:")

if st.button("Submit"):
    if query:
        try:
            # Send request to the backend API
            response = requests.post(API_URL, json={"query": query})
            
            # Display the response
            if response.status_code == 200:
                st.success("Response from NuBot:")
                st.write(response.json())
            else:
                st.error(f"Error {response.status_code}: {response.text}")
        except requests.exceptions.RequestException as e:
            st.error(f"Request failed: {e}")
    else:
        st.warning("Please enter a query before submitting.")
