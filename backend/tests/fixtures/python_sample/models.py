from dataclasses import dataclass

@dataclass
class User:
    id: int
    email: str
    hashed_password: str

@dataclass
class Product:
    id: int
    name: str
    price: float
