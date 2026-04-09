from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from route import health, logs, network, threats

app = FastAPI(title='Abeonasec API')

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_methods=['*'],
    allow_headers=['*'],
)

app.include_router(health.router)
app.include_router(logs.router)
app.include_router(network.router)
app.include_router(threats.router)
