# main.py
from contextlib import asynccontextmanager
from typing import Union, Optional, Annotated
from app import settings
from sqlmodel import Field, Session, SQLModel, create_engine, select, Sequence
from fastapi import FastAPI, Depends, HTTPException
from typing import AsyncGenerator
from aiokafka import AIOKafkaProducer, AIOKafkaConsumer
import asyncio
import json
from jose import JWTError
from datetime import timedelta
from app.utils import create_access_token, decode_access_token
from fastapi.security import OAuth2PasswordRequestForm , OAuth2PasswordBearer


fake_users_db: dict[str, dict[str, str]] = {
    "ameenalam": {
        "username": "ameenalam",
        "full_name": "Ameen Alam",
        "email": "ameenalam@example.com",
        "password": "ameenalamsecret",
    },
    "mjunaid": {
        "username": "mjunaid",
        "full_name": "Muhammad Junaid",
        "email": "mjunaid@example.com",
        "password": "mjunaidsecret",
    },
}



# only needed for psycopg 3 - replace postgresql
# with postgresql+psycopg in settings.DATABASE_URL


connection_string = str(settings.DATABASE_URL).replace(
    "postgresql", "postgresql+psycopg"
)


# recycle connections after 5 minutes
# to correspond with the compute scale down
engine = create_engine(
    connection_string, connect_args={}, pool_recycle=300
)

#engine = create_engine(
#    connection_string, connect_args={"sslmode": "require"}, pool_recycle=300
#)


def create_db_and_tables()->None:
    SQLModel.metadata.create_all(engine)

async def consume_messages(topic, bootstrap_servers):
    # Create a consumer instance.
    consumer = AIOKafkaConsumer(
        topic,
        bootstrap_servers=bootstrap_servers,
        group_id="my-group",
        auto_offset_reset='earliest'
    )

    # Start the consumer.
    await consumer.start()
    try:
        # Continuously listen for messages.
        async for message in consumer:
            print(f"Received message: {message.value.decode()} on topic {message.topic}")
            # Here you can add code to process each message.
            # Example: parse the message, store it in a database, etc.
    finally:
        # Ensure to close the consumer when done.
        await consumer.stop()


# The first part of the function, before the yield, will
# be executed before the application starts.
# https://fastapi.tiangolo.com/advanced/events/#lifespan-function
# loop = asyncio.get_event_loop()
@asynccontextmanager
async def lifespan(app: FastAPI)-> AsyncGenerator[None, None]:
    print("Creating tables..")
    # loop.run_until_complete(consume_messages('todos', 'broker:19092'))
    task = asyncio.create_task(consume_messages('todos', 'broker:19092'))
    create_db_and_tables()
    yield


app = FastAPI(lifespan=lifespan, title="Imriaz Mart API", 
    version="0.0.1",
    servers=[
        {
            "url": "http://127.0.0.1:8020", # ADD NGROK URL Here Before Creating GPT Action
            "description": "Development Server"
        }
        ])

def get_session():
    with Session(engine) as session:
        yield session

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")


@app.get("/")
def read_root():
    return {"App": "User"}


@app.post("/login")
def login(form_data: Annotated[OAuth2PasswordRequestForm, Depends(OAuth2PasswordRequestForm)]):
    """
    Understanding the login system
    -> Takes form_data that have username and password
    """
    user_in_fake_db = fake_users_db.get(form_data.username)
    if not user_in_fake_db:
        raise HTTPException(status_code=400, detail="Incorrect username")

    if not form_data.password == user_in_fake_db["password"]:
        raise HTTPException(status_code=400, detail="Incorrect password")

    access_token_expires = timedelta(minutes=1)

    access_token = create_access_token(
        subject=user_in_fake_db["username"], expires_delta=access_token_expires)

    return {"access_token": access_token, "token_type": "bearer", "expires_in": access_token_expires.total_seconds() }


@app.get("/get-access-token")
def get_access_token(user_name: str):
    """
    Understanding the access token
    -> Takes user_name as input and returns access token
    -> timedelta(minutes=1) is used to set the expiry time of the access token to 1 minute
    """

    access_token_expires = timedelta(minutes=1)
    access_token = create_access_token(
        subject=user_name, expires_delta=access_token_expires)

    return {"access_token": access_token}


@app.get("/decode_token")
def decoding_token(access_token: str):
    """
    Understanding the access token decoding and validation
    """
    try:
        decoded_token_data = decode_access_token(access_token)
        return {"decoded_token": decoded_token_data}
    except JWTError as e:
        return {"error": str(e)}

@app.get("/users/all")
def get_all_users():
    # Note: We never return passwords in a real application
    return fake_users_db

@app.get("/users/me")
def read_users_me(token: Annotated[str, Depends(oauth2_scheme)]):
    user_token_data = decode_access_token(token)
    
    user_in_db = fake_users_db.get(user_token_data["sub"])
    
    return user_in_db

# Kafka Producer as a dependency
async def get_kafka_producer():
    producer = AIOKafkaProducer(bootstrap_servers='broker:19092')
    await producer.start()
    try:
        yield producer
    finally:
        await producer.stop()


