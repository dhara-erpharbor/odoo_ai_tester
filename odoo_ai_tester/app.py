import streamlit as st
import zipfile
import io
import os
import re
import json
import time
import requests

# Enable browser networking when running in Pyodide/stlite
try:
    import pyodide_http
    pyodide_http.patch_all()
except ImportError:
    pass

st.set_page_config(page_title="Odoo AI Test Generator", page_icon="🤖", layout="wide")

st.title("🤖 Odoo AI Test Case Generator & Error Solver (Python & JS)")
st.markdown("""
This AI agent helps Odoo developers generate comprehensive test cases and fix existing test errors. 
It analyzes your module to generate **Python unit tests (`TransactionCase`), JavaScript frontend tests (Odoo Tours & QUnit), and access-rights/multi-company scenarios**.
""")

# Persistent Key Storage & Configuration
CONFIG_FILE = os.path.expanduser("~/.odoo_ai_tester_config.json")

def load_cached_keys():
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return {}

def save_cached_key(provider_key, key_value):
    try:
        data = load_cached_keys()
        data[provider_key] = key_value
        with open(CONFIG_FILE, "w") as f:
            json.dump(data, f)
    except Exception:
        pass

def get_default_key(secret_name, cache_key):
    # 1. Check Streamlit Secrets / Environment
    try:
        if hasattr(st, "secrets") and secret_name in st.secrets:
            return st.secrets[secret_name]
    except Exception:
        pass
    if os.environ.get(secret_name):
        return os.environ.get(secret_name)
    
    # 2. Check local persistent disk cache
    cached = load_cached_keys().get(cache_key, "")
    if cached:
        return cached
    return ""

if "gemini_key" not in st.session_state:
    st.session_state["gemini_key"] = get_default_key("GEMINI_API_KEY", "gemini")
if "groq_key" not in st.session_state:
    st.session_state["groq_key"] = get_default_key("GROQ_API_KEY", "groq")
if "openai_key" not in st.session_state:
    st.session_state["openai_key"] = get_default_key("OPENAI_API_KEY", "openai")

# Sidebar for Configuration
st.sidebar.header("Configuration")
provider = st.sidebar.selectbox(
    "AI Provider",
    ["Google Gemini (Free)", "Groq (Free)", "OpenAI (Paid)"]
)

if provider == "Google Gemini (Free)":
    api_key_input = st.sidebar.text_input(
        "Gemini API Key",
        value=st.session_state["gemini_key"],
        type="password",
        help="Free key from Google AI Studio"
    )
    if api_key_input != st.session_state["gemini_key"]:
        st.session_state["gemini_key"] = api_key_input
        save_cached_key("gemini", api_key_input)
    api_key = api_key_input
    st.sidebar.info("💡 [Get a Free Gemini Key](https://aistudio.google.com/app/apikey)")
    model_choice = st.sidebar.selectbox("Model", ["gemini-3.8-flash"])
    endpoint_url = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"

elif provider == "Groq (Free)":
    api_key_input = st.sidebar.text_input(
        "Groq API Key",
        value=st.session_state["groq_key"],
        type="password",
        help="Free key from Groq Console"
    )
    if api_key_input != st.session_state["groq_key"]:
        st.session_state["groq_key"] = api_key_input
        save_cached_key("groq", api_key_input)
    api_key = api_key_input
    st.sidebar.info("💡 [Get a Free Groq Key](https://console.groq.com/keys)")
    model_choice = st.sidebar.selectbox("Model", ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"])
    endpoint_url = "https://api.groq.com/openai/v1/chat/completions"

else:  # OpenAI (Paid)
    api_key_input = st.sidebar.text_input(
        "OpenAI API Key",
        value=st.session_state["openai_key"],
        type="password"
    )
    if api_key_input != st.session_state["openai_key"]:
        st.session_state["openai_key"] = api_key_input
        save_cached_key("openai", api_key_input)
    api_key = api_key_input
    model_choice = st.sidebar.selectbox("Model", ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo"])
    endpoint_url = "https://api.openai.com/v1/chat/completions"

# Option to clear saved keys
with st.sidebar.expander("Key Settings"):
    if st.button("Clear Saved Keys"):
        st.session_state["gemini_key"] = ""
        st.session_state["groq_key"] = ""
        st.session_state["openai_key"] = ""
        try:
            if os.path.exists(CONFIG_FILE):
                os.remove(CONFIG_FILE)
        except Exception:
            pass
        st.rerun()


def call_llm_chat(endpoint_url, api_key, model, messages, temperature=0.2):
    if not api_key:
        st.warning("Please enter your API key in the sidebar.")
        return None

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key.strip()}",
    }
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }

    last_error = None
    for attempt in range(2):
        try:
            # timeout=(60, None): 60s connect timeout, NO read timeout (will never time out waiting for code generation)
            response = requests.post(
                endpoint_url,
                json=payload,
                headers=headers,
                timeout=(60, None)
            )
            if response.status_code != 200:
                try:
                    err_data = response.json()
                    if isinstance(err_data, list) and len(err_data) > 0:
                        err_msg = err_data[0].get("error", {}).get("message", response.text)
                    elif isinstance(err_data, dict):
                        err_msg = err_data.get("error", {}).get("message", response.text)
                    else:
                        err_msg = response.text
                except Exception:
                    err_msg = response.text
                raise Exception(f"API Error ({response.status_code}): {err_msg}")

            data = response.json()
            return data["choices"][0]["message"]["content"]
        except requests.exceptions.Timeout as e:
            last_error = f"Connection timed out (attempt {attempt + 1}). Retrying..."
            time.sleep(2)
        except Exception as e:
            raise Exception(f"Request Error: {e}")

    raise Exception(f"Request Error: {last_error}")

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
            if not api_key:
                st.warning("Please enter your API key in the sidebar.")
            else:
                with st.spinner("Analyzing module and generating tests..."):
                    try:
                        module_files = extract_files_from_zip(uploaded_zip)
                        
                        # Filter relevant files: .py, .js, and UI .xml (ignore cache/hidden/venv/node_modules/min.js)
                        relevant_files = {}
                        for k, v in module_files.items():
                            if any(part in k for part in ['__pycache__', '/.', '\\.', 'site-packages', 'venv', 'node_modules', '.min.js', 'static/lib']):
                                continue
                            if k.endswith('.py') or k.endswith('.js') or (k.endswith('.xml') and ('static/src' in k or 'views' in k)):
                                relevant_files[k] = v.decode('utf-8', errors='ignore')
                        
                        context_text = ""
                        for path, content in relevant_files.items():
                            context_text += f"\\n--- {path} ---\\n{content}\\n"
                            
                        sys_prompt = """
                        You are an expert Odoo Full-Stack Developer and QA Engineer.
                        Your task is to review the provided Odoo module code and generate or fix comprehensive automated test cases covering BOTH Python and JavaScript wherever applicable.
                        
                        Requirements:
                        1. PYTHON BACKEND TESTS:
                           - Generate positive, negative, boundary, access-rights, and multi-company test scenarios.
                           - Draft Odoo tests using `TransactionCase`.
                           - CRITICAL: The test cases MUST NOT use `sudo()` anywhere.
                           - Provide or update `tests/__init__.py` to import all Python test files.
                        
                        2. JAVASCRIPT FRONTEND & TOUR TESTS (Whenever UI, views, controllers, or frontend JS/OWL exist):
                           - Create Odoo Tour test files (e.g., `static/src/js/tours/test_something.js` or `static/tests/tours/test_something.js`) to simulate user workflows (clicking buttons, filling forms, checking error notifications).
                           - Provide the corresponding Python test runner file using `HttpCase` (e.g., `tests/test_tour.py`) with `self.start_tour(...)`.
                           - For custom OWL components or widgets, generate QUnit / OWL component unit tests.
                           - If the module is strictly backend-only (no UI/actions/views), state that JS tests are not required.
                        
                        3. Map each requirement to a test case in your explanation.
                        4. Highlight requirements that have no corresponding test.
                        5. If tests already exist, review them, fix any errors, and add missing scenarios.
                        
                        Output format:
                        Provide your analysis and requirement mapping in markdown.
                        Whenever you need to create or update a file, wrap the exact file content like this:
                        [FILE: module_name/tests/test_something.py]
                        # file content here
                        [/FILE]
                        
                        [FILE: module_name/static/src/js/tours/test_something.js]
                        // js tour content here
                        [/FILE]
                        """
                        
                        user_prompt = f"Here is the module code:\\n{context_text}\\nPlease generate or update the tests based on the requirements. Pay attention to the directory structure and paths used in the provided code."
                        
                        full_response = call_llm_chat(
                            endpoint_url=endpoint_url,
                            api_key=api_key,
                            model=model_choice,
                            messages=[
                                {"role": "system", "content": sys_prompt},
                                {"role": "user", "content": user_prompt}
                            ],
                            temperature=0.2
                        )
                        if full_response:
                            explanation, updated_files = parse_llm_response(full_response)
                        
                        st.markdown("### Analysis & Requirement Mapping")
                        st.markdown(explanation)
                        
                        if updated_files:
                            st.markdown("### Generated / Updated Files")
                            for path, content in updated_files.items():
                                lang = "javascript" if path.endswith('.js') else ("xml" if path.endswith('.xml') else "python")
                                with st.expander(f"📄 {path}"):
                                    st.code(content, language=lang)
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
        elif not api_key:
            st.warning("Please enter your API key in the sidebar.")
        else:
            with st.spinner("Generating tests..."):
                try:
                    sys_prompt = """
                    You are an expert Odoo Full-Stack Developer and QA Engineer.
                    Your task is to generate Odoo test cases based on the provided task description, feature spec, Python method, or JavaScript component.
                    
                    Requirements:
                    1. PYTHON BACKEND TESTS:
                       - Generate positive, negative, boundary, access-rights, and multi-company test scenarios using `TransactionCase`.
                       - CRITICAL: The test cases MUST NOT use `sudo()` anywhere.
                    
                    2. JAVASCRIPT FRONTEND & TOUR TESTS (Whenever UI, views, controllers, or frontend JS/OWL are involved):
                       - Create an Odoo JavaScript Tour (e.g. `web.tour` / `registry.category("web_tour.tours")`) to validate user interactions and flows.
                       - Provide the corresponding Python test runner using `HttpCase` (`self.start_tour(...)`).
                       - For custom OWL components or widgets, generate QUnit / OWL component unit tests.
                    
                    3. Map each requirement to a test case in your explanation.
                    
                    Provide your analysis first, followed by the Python and JavaScript test code in standard markdown code blocks with clear file path suggestions.
                    """
                    
                    user_prompt = f"Input:\n{text_input}\nPlease generate the tests based on the requirements."
                    
                    full_response = call_llm_chat(
                        endpoint_url=endpoint_url,
                        api_key=api_key,
                        model=model_choice,
                        messages=[
                            {"role": "system", "content": sys_prompt},
                            {"role": "user", "content": user_prompt}
                        ],
                        temperature=0.2
                    )
                    
                    if full_response:
                        st.markdown(full_response)
                except Exception as e:
                    st.error(f"An error occurred: {e}")

