import os

import streamlit as st
from dotenv import load_dotenv
from streamlit.errors import StreamlitSecretNotFoundError

load_dotenv()


def configure_api_key() -> bool:
    if os.getenv("GROQ_API_KEY") or os.getenv("ANTHROPIC_API_KEY"):
        return True

    for name in ("GROQ_API_KEY", "ANTHROPIC_API_KEY"):
        try:
            api_key = st.secrets[name]
        except KeyError:
            continue
        except StreamlitSecretNotFoundError:
            return False
        if api_key:
            os.environ[name] = str(api_key)
            return True
    return False


has_api_key = configure_api_key()

import app as backend

st.set_page_config(page_title="Medication Leaflet Assistant", page_icon="💊")
st.title("Medication Leaflet Assistant")
st.caption(
    "Ask questions about the leaflet you provide. This tool is not medical advice; "
    "for urgent symptoms, contact your local emergency service."
)

st.session_state.setdefault("messages", [])
st.session_state.setdefault("leaflet_text", "")
st.session_state.setdefault("active_leaflet_text", st.session_state["leaflet_text"])


def load_sample_leaflet() -> None:
    st.session_state["leaflet_text"] = backend.SAMPLE_LEAFLET


def clear_chat() -> None:
    st.session_state["messages"] = []


with st.sidebar:
    st.header("Leaflet")
    st.button("Load fictional sample", on_click=load_sample_leaflet)
    leaflet_text = st.text_area(
        "Paste leaflet text",
        key="leaflet_text",
        height=320,
        max_chars=backend.MAX_LEAFLET_CHARS,
        help=f"Up to {backend.MAX_LEAFLET_CHARS:,} characters.",
    )
    st.caption(f"{len(leaflet_text):,} / {backend.MAX_LEAFLET_CHARS:,} characters")
    language = st.selectbox("Answer language", ("English", "Arabic"))
    level = st.selectbox("Reading level", ("Simple", "Standard"))
    st.button("Clear conversation", on_click=clear_chat)

    if not has_api_key:
        st.warning("Configure GROQ_API_KEY in Streamlit Secrets or your local .env file to enable model answers.")

if st.session_state["active_leaflet_text"] != leaflet_text:
    st.session_state["messages"] = []
    st.session_state["active_leaflet_text"] = leaflet_text


def render_message(message: dict) -> None:
    with st.chat_message(message["role"]):
        if message.get("status"):
            st.caption(f"Status: {message['status']}")
        if message.get("status") == "urgent":
            st.warning(message["content"])
        elif message.get("status") == "error":
            st.error(message["content"])
        else:
            st.markdown(message["content"])

        for source in message.get("sources", []):
            with st.expander(f"[{source['id']}] {source['section']}"):
                st.write(source["text"])

        for quote in message.get("quotes", []):
            st.caption(f'Leaflet quote: "{quote}"')


for chat_message in st.session_state["messages"]:
    render_message(chat_message)

question = st.chat_input(
    "Ask about a warning, side effect, or term",
    disabled=not leaflet_text.strip(),
)
if question:
    st.session_state["messages"].append({"role": "user", "content": question})
    with st.spinner("Checking the leaflet..."):
        result = backend.chat(
            backend.ChatRequest(
                message=question,
                leaflet_text=leaflet_text,
                language=language,
                level=level,
            )
        )
    st.session_state["messages"].append(
        {
            "role": "assistant",
            "content": result.reply,
            "status": result.status,
            "sources": result.sources,
            "quotes": result.quotes,
        }
    )
    st.rerun()
