from fastapi import FastAPI, Query, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel
from typing import Optional
from jose import jwt, JWTError
from passlib.context import CryptContext
import random
import datetime




app = FastAPI()

# -------------------------------------------------------------
# BASES DE DATOS TEMPORALES (EN MEMORIA)
# -------------------------------------------------------------
missions_db = {}
data_db = []
simulations_db = []
users_db = {}  # base de datos para usuarios


# -------------------------------------------------------------
# CONFIGURACIÓN DE SEGURIDAD (JWT)
# -------------------------------------------------------------
SECRET_KEY = "SUPER_SECRET_KEY_123"
ALGORITHM = "HS256"

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/v1/auth/login")


def hash_password(password: str):
    return pwd_context.hash(password)


def verify_password(password: str, hashed: str):
    return pwd_context.verify(password, hashed)


def create_jwt(data: dict):
    return jwt.encode(data, SECRET_KEY, algorithm=ALGORITHM)


def decode_jwt(token: str):
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None


def get_current_user(token: str = Depends(oauth2_scheme)):
    payload = decode_jwt(token)

    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    email = payload.get("sub")

    if email not in users_db:
        raise HTTPException(status_code=404, detail="User not found")

    return users_db[email]


# -------------------------------------------------------------
# MODELOS DE DATOS
# -------------------------------------------------------------
class UploadData(BaseModel):
    mission_id: str
    timestamp: str
    gps_lat: float
    gps_lon: float
    gps_alt: Optional[float] = None
    sensor_type: str
    data_url: Optional[str] = None


class Mission(BaseModel):
    mission_id: str
    type: str
    start_time: str
    status: str
    progress: int


class UserSignup(BaseModel):
    first_name: str
    last_name: str
    email: str
    password: str


class UserLogin(BaseModel):
    email: str
    password: str


# -------------------------------------------------------------
# CORS
# -------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,    
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],  # Déjalo solo con "*"
    allow_origins=["https://prueba-tech-rl2t.onrender.com",
                   "http://localhost:5173",]  
)


# =============================================================
#                AUTENTICACIÓN (SIGNUP / LOGIN)
# =============================================================

@app.post("/api/v1/auth/signup")
def signup(user: UserSignup):
    if user.email in users_db:
        raise HTTPException(status_code=400, detail="Email already registered")

    users_db[user.email] = {
        "first_name": user.first_name,
        "last_name": user.last_name,
        "email": user.email,
        "password": hash_password(user.password)
    }

    return {
        "status": "success",
        "message": "User registered successfully"
    }


@app.post("/api/v1/auth/login")
def login(credentials: UserLogin):
    user = users_db.get(credentials.email)

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if not verify_password(credentials.password, user["password"]):
        raise HTTPException(status_code=401, detail="Incorrect password")

    token = create_jwt({"sub": credentials.email})

    return {
        "status": "success",
        "access_token": token,
        "token_type": "Bearer"
    }


@app.get("/api/v1/auth/me")
def get_me(user=Depends(get_current_user)):
    return {
        "email": user["email"],
        "first_name": user["first_name"],
        "last_name": user["last_name"]
    }


# =============================================================
#                   ENDPOINTS ORIGINALES
# =============================================================

@app.post("/api/v1/data/upload")
def upload_data(data: UploadData, user=Depends(get_current_user)):
    data_db.append(data.dict())
    return {
        "status": "success",
        "message": "Data received successfully",
        "received": data
    }


@app.get("/api/v1/missions/{mission_id}/status")
def get_mission_status(mission_id: str, user=Depends(get_current_user)):
    if mission_id not in missions_db:
        raise HTTPException(status_code=404, detail=f"Mission '{mission_id}' not found")
    return missions_db[mission_id]


@app.get("/api/v1/data/query")
def query_data(
    start_date: Optional[str] = Query(None),
    sensor_type: Optional[str] = Query(None),
    lat: Optional[float] = Query(None),
    lon: Optional[float] = Query(None),
    user=Depends(get_current_user)
):
    """
    Buscar y filtrar misiones por fecha, tipo de sensor o posición GPS.
    Funciona con cualquier combinación de filtros.
    """
    # --- IMPORTANTE: trabajar sobre las misiones simuladas ---
    results = list(missions_db.values())

    # -------------------------
    # FILTRO: FECHA DE INICIO
    # -------------------------
    if start_date:
        results = [
            r for r in results
            if r.get("timestamp") and r["timestamp"] >= start_date
        ]

    # -------------------------
    # FILTRO: TIPO DE SENSOR
    # -------------------------
    if sensor_type:
        results = [
            r for r in results
            if r.get("sensor_type") == sensor_type
        ]

    # -------------------------
    # FILTRO: LATITUD
    # -------------------------
    if lat is not None:
        tolerance = 0.001  # ~111 metros
        results = [
            r for r in results
            if "gps_lat" in r and abs(r["gps_lat"] - lat) <= tolerance
        ]

    # -------------------------
    # FILTRO: LONGITUD
    # -------------------------
    if lon is not None:
        tolerance = 0.001
        results = [
            r for r in results
            if "gps_lon" in r and abs(r["gps_lon"] - lon) <= tolerance
        ]

    return {
        "filters_applied": {
            "start_date": start_date,
            "sensor_type": sensor_type,
            "lat": lat,
            "lon": lon
        },
        "total_found": len(results),
        "results": results
    }

# =============================================================
#                 SIMULACIÓN DE MISIONES
# =============================================================

@app.post("/api/v1/simulate/{num}")
def simulate_missions(num: int, user=Depends(get_current_user)):
    """
    Genera 'num' misiones simuladas y las guarda tanto en missions_db como en simulations_db.
    Cada misión contiene tipo de sensor, fecha, posición GPS y estado.
    """

    mission_types = ["thermal", "multispectral", "lidar"]
    created_missions = []

    for _ in range(num):
        # ID correlativo de misión
        next_id = len(missions_db) + 1
        mission_id = f"M{1000 + next_id}"

        # Fecha aleatoria dentro del 2025
        start_time_dt = (
            datetime.datetime(2025, 1, 1)
            + (datetime.datetime(2025, 12, 31) - datetime.datetime(2025, 1, 1)) * random.random()
        )
        start_time = start_time_dt.replace(microsecond=0).isoformat() + "Z"

        # Estado aleatorio
        status = random.choice(["pending", "processing", "completed"])

        # Tipo de sensor coherente
        sensor_type = random.choice(mission_types)

        # GPS aleatorio dentro de Colombia
        gps_lat = round(random.uniform(4.0, 6.0), 6)
        gps_lon = round(random.uniform(-75.5, -73.5), 6)

        # Construimos la misión
        mission = {
            "mission_id": mission_id,
            "sensor_type": sensor_type,
            "type": sensor_type,               # coherente para filtrado
            "timestamp": start_time,
            "start_time": start_time,
            "gps_lat": gps_lat,
            "gps_lon": gps_lon,
            "status": status,
            "progress": random.randint(0, 100)
        }

        # Si está completada, generamos end_time
        if status == "completed":
            end_time_dt = start_time_dt + datetime.timedelta(minutes=random.randint(1, 180))
            mission["end_time"] = end_time_dt.replace(microsecond=0).isoformat() + "Z"

        # Guardamos
        missions_db[mission_id] = mission
        created_missions.append(mission)

    # Guardamos la simulación completa
    simulation_result = {
        "simulation_id": len(simulations_db) + 1,
        "missions_generated": num,
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
        "missions": created_missions
    }

    simulations_db.append(simulation_result)

    return simulation_result




@app.get("/api/v1/simulations")
def get_simulations(user=Depends(get_current_user)):
    return simulations_db


