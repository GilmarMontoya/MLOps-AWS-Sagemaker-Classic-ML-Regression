# Consumo del endpoint de Linear Learner

App web (Streamlit) que manda casas al endpoint de SageMaker y devuelve el precio predicho.

| Archivo | Para qué |
|---|---|
| `app_frontend_de_consumo_linear.py` | La app que se ejecuta (pantalla web) |
| `app_backend_de_consumo_linear.py` | Lógica que llama al endpoint (la usa el frontend) |
| `prueba-una-casa.csv` | CSV de ejemplo para subir a la app |
| `.env` | Credenciales, región (`us-east-2`) y nombre del endpoint. No se sube a git |

## Pasos

```bash
conda activate MLOps-AWS-Regresion-Houses
pip install -r requirements.txt          # solo la primera vez
streamlit run app_frontend_de_consumo_linear.py
```

Se abre en http://localhost:8501. Sube `prueba-una-casa.csv` y aprieta **Generar Predicciones**.

> El endpoint tiene que estar en **InService** (se publica desde `linear-learner-houses-LOCAL.ipynb`).
> Cuando termines, bórralo con la última celda del notebook: cuesta ~US$0.24/h.
