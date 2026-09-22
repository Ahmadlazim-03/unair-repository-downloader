"""Hugging Face Space entrypoint."""
import os
import uvicorn
import gradio as gr
from backend.app import app

PORT = int(os.getenv("PORT", "7860"))

with gr.Blocks(title="UNAIR Repository Downloader API") as demo:
    gr.Markdown(
        "# 📚 UNAIR Repository Downloader Backend API\n\n"
        "Backend sedang berjalan normal.\n\n"
        "- Endpoint API FastAPI aktif di `/health`, `/jobs`, `/vpn/profiles`.\n"
        "- Gunakan frontend web Vercel untuk mengunduh dokumen."
    )

app = gr.mount_gradio_app(app, demo, path="/")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT, timeout_graceful_shutdown=120)
