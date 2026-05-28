import uvicorn

def serve():
    uvicorn.run(
        "chongming_gateway.app:app", 
        host="0.0.0.0", 
        port=8000,
        reload=True
    )

def gunicorn_serve():
    import sys
    from gunicorn.app.wsgiapp import run

    sys.argv = [
        "gunicorn",
        "chongming_gateway.app:app",
        "-k",
        "uvicorn.workers.UvicornWorker",
        "-w",
        "4",
        "-b",
        "0.0.0.0:8000",
    ]
    run()