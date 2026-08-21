"""
Frontend Streamlit para consumir el endpoint de Linear Learner.
Permite subir un CSV y obtener predicciones del modelo desplegado en SageMaker.
"""
import os
import streamlit as st
import pandas as pd
import numpy as np
from dotenv import load_dotenv
from app_backend_de_consumo_linear import SageMakerPredictor

load_dotenv()

# Configuración de la página
st.set_page_config(
    page_title="Predicción con Linear Learner",
    page_icon="🤖",
    layout="wide"
)

# Título principal
st.title("🤖 Predicción con Modelo Linear Learner")
st.markdown("---")

# Sidebar para configuración
with st.sidebar:
    st.header("⚙️ Configuración")
    
    # Credenciales de AWS (en producción usar secrets o variables de entorno)
    st.subheader("Credenciales AWS")
    aws_access_key_id = st.text_input(
        "AWS Access Key ID",
        value=os.getenv("AWS_ACCESS_KEY_ID", ""),
        type="password"
    )
    aws_secret_access_key = st.text_input(
        "AWS Secret Access Key",
        value=os.getenv("AWS_SECRET_ACCESS_KEY", ""),
        type="password"
    )
    region_name = st.text_input(
        "Región AWS",
        value=os.getenv("AWS_REGION", "us-east-2")
    )

    # Nombre del endpoint
    st.subheader("Endpoint")
    endpoint_name = st.text_input(
        "Nombre del Endpoint",
        value=os.getenv("SAGEMAKER_ENDPOINT_NAME", "")
    )

# Sección principal: carga de archivo
st.header("📁 Carga de Datos")

uploaded_file = st.file_uploader(
    "Sube tu archivo CSV con las features del modelo",
    type=["csv"],
    help="El CSV debe contener todas las columnas necesarias para el modelo"
)

if uploaded_file is not None:
    try:
        # Leemos el CSV con pandas
        df = pd.read_csv(uploaded_file)
        
        st.success(f"✅ Archivo cargado exitosamente: {len(df)} filas, {len(df.columns)} columnas")
        
        # Mostramos una vista previa de los datos
        st.subheader("📊 Vista Previa de los Datos")
        st.dataframe(df.head(10), width='stretch')
        
        # Información sobre las columnas
        with st.expander("ℹ️ Información de Columnas"):
            st.write(f"**Número de columnas:** {len(df.columns)}")
            st.write(f"**Nombres de columnas:** {list(df.columns)}")
            st.write(f"**Tipos de datos:**")
            # Convertimos los tipos a string para evitar problemas con PyArrow
            tipos_df = df.dtypes.to_frame("Tipo")
            tipos_df["Tipo"] = tipos_df["Tipo"].astype(str)
            st.dataframe(tipos_df, width='stretch')
            
            # Advertencia si no tiene exactamente 16 columnas
            if len(df.columns) != 16:
                if len(df.columns) >= 19:
                    cols_usadas = list(df.columns[3:19])
                    st.warning(
                        f"⚠️ El CSV tiene {len(df.columns)} columnas. Se descartarán las "
                        f"**primeras 3** ({', '.join(df.columns[:3])}) y las **últimas "
                        f"{len(df.columns) - 19}** ({', '.join(df.columns[19:])}). "
                        f"Se usarán las 16 columnas: {', '.join(cols_usadas)}."
                    )
                elif len(df.columns) > 16:
                    st.error(
                        f"❌ El CSV tiene {len(df.columns)} columnas pero el layout "
                        f"esperado requiere 16 (solo features) o ≥19 (dataset original "
                        f"con id/date/price al inicio y sqft_living15/sqft_lot15 al final)."
                    )
                else:
                    st.error(f"❌ El CSV debe tener al menos 16 columnas. Se encontraron {len(df.columns)} columnas.")
        
        # Botón para hacer predicciones
        st.markdown("---")
        st.subheader("🔮 Predicciones")
        
        if st.button("🚀 Generar Predicciones", type="primary", use_container_width=True):
            # Validamos que tengamos credenciales y endpoint
            if not aws_access_key_id or not aws_secret_access_key or not endpoint_name:
                st.error("❌ Por favor completa todas las credenciales y el nombre del endpoint en el sidebar")
            else:
                try:
                    # Validamos layout: 16 columnas (solo features) o >=19 (dataset original)
                    if len(df.columns) < 16 or (16 < len(df.columns) < 19):
                        st.error(
                            f"❌ Layout inválido: el CSV debe tener 16 columnas (solo features) "
                            f"o ≥19 columnas (dataset original). Se encontraron {len(df.columns)}."
                        )
                        st.info("💡 El modelo Linear Learner espera 16 features numéricas (columnas 3 a 18 del dataset original)")
                    else:
                        # Inicializamos el predictor
                        with st.spinner("⏳ Inicializando conexión con SageMaker..."):
                            predictor = SageMakerPredictor(
                                endpoint_name=endpoint_name,
                                aws_access_key_id=aws_access_key_id,
                                aws_secret_access_key=aws_secret_access_key,
                                region_name=region_name
                            )
                        
                        # Creamos una barra de progreso
                        progress_bar = st.progress(0)
                        status_text = st.empty()

                        # Usamos la función del backend que procesa el DataFrame correctamente
                        total_rows = len(df)
                        status_text.text(f"Procesando {total_rows} filas en lotes...")

                        def _update_progress(done: int, total: int) -> None:
                            progress_bar.progress(done / total if total else 1.0)
                            status_text.text(f"Procesando {done}/{total} filas...")

                        # Procesamos y hacemos las predicciones en lotes paralelos
                        result_df, used_columns = predictor.predict_from_dataframe(
                            df,
                            chunk_size=500,
                            max_workers=8,
                            progress_callback=_update_progress,
                        )

                        # Actualizamos la barra de progreso
                        progress_bar.progress(1.0)
                        status_text.text("✅ Procesamiento completado")
                        
                        # Limpiamos la barra de progreso
                        progress_bar.empty()
                        status_text.empty()
                        
                        st.success(f"✅ Predicciones completadas exitosamente para {len(result_df)} filas")
                        
                        # Mostramos información sobre las columnas usadas
                        if len(df.columns) > 16:
                            st.info(f"ℹ️ Se usaron las siguientes {len(used_columns)} columnas para las predicciones: {', '.join(used_columns)}")
                        
                        # Mostramos los resultados
                        st.subheader("📈 Resultados")
                        st.dataframe(result_df, width='stretch')
                    
                        # Estadísticas de las predicciones
                        if "prediccion" in result_df.columns:
                            valid_predictions = result_df["prediccion"].dropna().tolist()
                            if valid_predictions:
                                col1, col2, col3, col4 = st.columns(4)
                                with col1:
                                    st.metric("Total Predicciones", len(valid_predictions))
                                with col2:
                                    st.metric("Promedio", f"{np.mean(valid_predictions):.2f}")
                                with col3:
                                    st.metric("Mínimo", f"{np.min(valid_predictions):.2f}")
                                with col4:
                                    st.metric("Máximo", f"{np.max(valid_predictions):.2f}")
                        
                        # Opción para descargar resultados
                        st.markdown("---")
                        st.subheader("💾 Descargar Resultados")
                        csv_result = result_df.to_csv(index=False)
                        st.download_button(
                            label="📥 Descargar CSV con Predicciones",
                            data=csv_result,
                            file_name="predicciones_linear_learner.csv",
                            mime="text/csv",
                            use_container_width=True
                        )
                    
                except Exception as e:
                    st.error(f"❌ Error al conectar con el endpoint: {str(e)}")
                    st.info("💡 Verifica que las credenciales y el nombre del endpoint sean correctos")
    
    except Exception as e:
        st.error(f"❌ Error al leer el archivo CSV: {str(e)}")
        st.info("💡 Asegúrate de que el archivo sea un CSV válido")

else:
    # Mensaje cuando no hay archivo cargado
    st.info("👆 Por favor sube un archivo CSV para comenzar")
    
    # Ejemplo de formato esperado
    with st.expander("📝 Información sobre el formato CSV esperado"):
        st.markdown("""
        ### Requisitos del CSV
        
        El modelo **Linear Learner** espera exactamente **16 columnas numéricas**.
        
        **Importante:**
        - Si tu CSV tiene **exactamente 16 columnas**, se usarán todas
        - Si tu CSV tiene **más de 16 columnas**, se usarán las **primeras 16 columnas**
        - Si tu CSV tiene **menos de 16 columnas**, no se podrán hacer predicciones
        
        ### Columnas esperadas (en orden)
        
        Estas son las 16 features que el modelo espera (basadas en el dataset original):
        
        1. `bedrooms`: Número de habitaciones
        2. `bathrooms`: Número de baños  
        3. `sqft_living`: Pies cuadrados de área habitable
        4. `sqft_lot`: Pies cuadrados de lote
        5. `floors`: Número de pisos
        6. `waterfront`: Indicador de frente al agua (0 o 1)
        7. `view`: Vista (0-4)
        8. `condition`: Condición (1-5)
        9. `grade`: Grado (1-13)
        10. `sqft_above`: Pies cuadrados sobre el nivel del suelo
        11. `sqft_basement`: Pies cuadrados del sótano
        12. `yr_built`: Año de construcción
        13. `yr_renovated`: Año de renovación
        14. `zipcode`: Código postal
        15. `lat`: Latitud
        16. `long`: Longitud
        
        ### Ejemplo de fila CSV
        
        ```
        3,1.00,1180,5650,1.0,0,0,3,7,1180,0,1955,0,98178,47.5112,-122.257
        ```
        
        **Nota:** El procesamiento automático convertirá todas las columnas a valores numéricos y rellenará valores faltantes con 0.
        """)

# Footer
st.markdown("---")
st.markdown(
    "<div style='text-align: center; color: gray;'>"
    "Powered by AWS SageMaker Linear Learner 🤖"
    "</div>",
    unsafe_allow_html=True
)
