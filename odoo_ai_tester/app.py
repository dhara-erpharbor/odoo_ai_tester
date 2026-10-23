import streamlit as st
import zipfile
import io
import os
import re
from openai import OpenAI

st.set_page_config(page_title="Odoo AI Test Generator", page_icon="🤖", layout="wide")

st.title("🤖 Odoo AI Test Case Generator & Error Solver")
st.markdown("""
This AI agent helps Odoo developers generate comprehensive test cases and fix existing test errors. 
It analyzes your module to generate **positive, negative, boundary, access-rights, and multi-company test scenarios**.
""")

# Sidebar for Configuration
st.sidebar.header("Configuration")
api_key = st.sidebar.text_input("OpenAI API Key", type="password")
model_choice = st.sidebar.selectbox("Model", ["gpt-4o", "gpt-4-turbo", "gpt-3.5-turbo"])

def get_openai_client():
    if not api_key:
        st.warning("Please enter your OpenAI API key in the sidebar.")
        return None
    return OpenAI(api_key=api_key)

def extract_files_from_zip(uploaded_file):
    with zipfile.ZipFile(uploaded_file, "r") as z:
        files = {name: z.read(name) for name in z.namelist() if not name.endswith('/')}
    return files

def create_zip_file(files_dict):
    memory_file = io.BytesIO()
    with zipfile.ZipFile(memory_file, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path, file_content in files_dict.items():
            if isinstance(file_content, str):
                file_content = file_content.encode('utf-8')
            zf.writestr(file_path, file_content)
    memory_file.seek(0)
    return memory_file

def parse_llm_response(response_text):
    # Extracts code blocks wrapped in [FILE: filepath] ... [/FILE]
    pattern = re.compile(r'\[FILE:\s*(.+?)\](.*?)\[/FILE\]', re.DOTALL)
    files_to_update = {}
    
    # Also extract the general markdown response (everything else)
    # We'll just remove the file blocks to show the rest as explanation
    explanation = re.sub(pattern, '', response_text).strip()
    
    for match in pattern.finditer(response_text):
        file_path = match.group(1).strip()
        file_content = match.group(2).strip()
        files_to_update[file_path] = file_content
        
    return explanation, files_to_update

tab1, tab2 = st.tabs(["Upload Module (ZIP)", "Input Code / Description"])

with tab1:
    st.subheader("Upload an Odoo Module ZIP")
    st.markdown("Upload your Odoo module. The AI will analyze `.py` files, review existing tests (or generate new ones), and provide a downloadable ZIP with the updated tests.")
    uploaded_zip = st.file_uploader("Choose a ZIP file", type=["zip"])
    
    if uploaded_zip is not None:
        if st.button("Analyze and Generate Tests (ZIP)", type="primary"):
            client = get_openai_client()
            if client:
                with st.spinner("Analyzing module and generating tests..."):
                    try:
                        module_files = extract_files_from_zip(uploaded_zip)
                        
                        # Filter to only .py files for context (to save tokens)
                        py_files = {k: v.decode('utf-8', errors='ignore') for k, v in module_files.items() if k.endswith('.py')}
                        
                        context_text = ""
                        for path, content in py_files.items():
                            context_text += f"\\n--- {path} ---\\n{content}\\n"
                            
                        sys_prompt = """
                        You are an expert Odoo Developer and QA Engineer.
                        Your task is to review the provided Odoo module code and generate or fix test cases.
                        
                        Requirements:
                        1. Generate positive, negative, boundary, access-rights, and multi-company test scenarios.
                        2. Draft Odoo tests using the appropriate testing framework (e.g., TransactionCase).
                        3. Map each requirement to a test case in your explanation.
                        4. Highlight requirements that have no corresponding test.
                        5. CRITICAL: The test cases MUST NOT use `sudo()` anywhere.
                        6. If tests already exist, review them, fix any errors, and add missing scenarios.
                        7. Make sure you also provide the `tests/__init__.py` file if it's missing or needs updating to import new test files.
                        
                        Output format:
                        Provide your analysis and requirement mapping in markdown.
                        Whenever you need to create or update a file, wrap the exact file content like this:
                        [FILE: module_name/tests/test_something.py]
                        # file content here
                        [/FILE]
                        """
                        
                        user_prompt = f"Here is the module code:\\n{context_text}\\nPlease generate or update the tests based on the requirements. Pay attention to the directory structure and paths used in the provided code."
                        
                        response = client.chat.completions.create(
                            model=model_choice,
                            messages=[
                                {"role": "system", "content": sys_prompt},
                                {"role": "user", "content": user_prompt}
                            ],
                            temperature=0.2
                        )
                        
                        full_response = response.choices[0].message.content
                        explanation, updated_files = parse_llm_response(full_response)
                        
                        st.markdown("### Analysis & Requirement Mapping")
                        st.markdown(explanation)
                        
                        if updated_files:
                            st.markdown("### Generated / Updated Files")
                            for path, content in updated_files.items():
                                with st.expander(f"📄 {path}"):
                                    st.code(content, language="python")
                                # Update the zip files dict
                                module_files[path] = content
                                
                            # Provide download button
                            new_zip = create_zip_file(module_files)
                            st.download_button(
                                label="Download Updated Module ZIP",
                                data=new_zip,
                                file_name=f"updated_{uploaded_zip.name}",
                                mime="application/zip",
                                type="primary"
                            )
                        else:
                            st.info("No files were generated or updated.")
                            
                    except Exception as e:
                        st.error(f"An error occurred: {e}")

with tab2:
    st.subheader("Generate Tests from Text / Snippet")
    st.markdown("Paste a task description, feature specification, or a specific Python method to generate standalone test scenarios.")
    text_input = st.text_area("Task Description or Python Code", height=200)
    
    if st.button("Generate Tests (Text)", type="primary"):
        if not text_input.strip():
            st.warning("Please enter some text or code.")
        else:
            client = get_openai_client()
            if client:
                with st.spinner("Generating tests..."):
                    try:
                        sys_prompt = """
                        You are an expert Odoo Developer and QA Engineer.
                        Your task is to generate Odoo test cases based on the provided task description, feature spec, or Python method.
                        
                        Requirements:
                        1. Generate positive, negative, boundary, access-rights, and multi-company test scenarios.
                        2. Draft Odoo tests using the appropriate testing framework (e.g., TransactionCase).
                        3. Map each requirement to a test case in your explanation.
                        4. Highlight requirements that have no corresponding test.
                        5. CRITICAL: The test cases MUST NOT use `sudo()` anywhere.
                        
                        Provide your analysis first, followed by the Python test code in a standard markdown code block.
                        """
                        
                        user_prompt = f"Input:\\n{text_input}\\nPlease generate the tests based on the requirements."
                        
                        response = client.chat.completions.create(
                            model=model_choice,
                            messages=[
                                {"role": "system", "content": sys_prompt},
                                {"role": "user", "content": user_prompt}
                            ],
                            temperature=0.2
                        )
                        
                        st.markdown(response.choices[0].message.content)
                    except Exception as e:
                        st.error(f"An error occurred: {e}")
