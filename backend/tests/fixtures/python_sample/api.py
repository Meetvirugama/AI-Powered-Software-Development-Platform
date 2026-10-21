from fastapi import FastAPI

app = FastAPI()

@app.get("/users")
def get_users():
    """FastAPI route to get all users."""
    return [{"id": 1, "name": "John"}]

@app.post("/users")
def create_user():
    """FastAPI route to create a user."""
    return {"status": "success"}
