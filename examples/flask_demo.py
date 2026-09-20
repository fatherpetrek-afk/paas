from flask import Flask

app = Flask(__name__)


@app.get("/")
def home():
    return "<h1>PaaS</h1><p>ok</p>"


if __name__ == "__main__":
    app.run()
