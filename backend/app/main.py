from fastapi import FastAPI

app = FastAPI(title='Graham Analyzer')

@app.get('/')
def read_root():
    return {'message': 'Graham Analyzer APIis running'}

