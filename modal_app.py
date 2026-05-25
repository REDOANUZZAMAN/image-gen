import io
import os

import modal

app = modal.App("flux-image-gen")

image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install(
        "torch==2.3.0",
        "diffusers==0.30.0",
        "transformers==4.44.0",
        "accelerate==0.33.0",
        "sentencepiece==0.2.0",
        "protobuf==5.27.2",
        "fastapi[standard]",
    )
)

with image.imports():
    import torch
    from diffusers import FluxPipeline


@app.cls(
    image=image,
    gpu="L4",
    timeout=600,
    scaledown_window=300,
    secrets=[modal.Secret.from_name("image-gen-api-key")],
)
class FluxModel:
    @modal.enter()
    def load_model(self):
        self.pipe = FluxPipeline.from_pretrained(
            "black-forest-labs/FLUX.1-schnell",
            torch_dtype=torch.bfloat16,
        ).to("cuda")

    @modal.method()
    def generate(self, prompt: str, steps: int = 4):
        img = self.pipe(
            prompt,
            num_inference_steps=steps,
            guidance_scale=0.0,
        ).images[0]
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()


@app.function(image=image, secrets=[modal.Secret.from_name("image-gen-api-key")])
@modal.fastapi_endpoint(method="POST")
def generate_image(prompt: str, api_key: str):
    from fastapi.responses import Response

    if api_key != os.environ["API_KEY"]:
        return Response(content="Unauthorized", status_code=401)

    image_bytes = FluxModel().generate.remote(prompt)
    return Response(content=image_bytes, media_type="image/png")
