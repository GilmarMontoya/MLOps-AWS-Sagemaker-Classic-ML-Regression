"""
Reimplementacion local y minima del algoritmo `linear-learner` de SageMaker.

Replica las decisiones que toma el algoritmo nativo de AWS con los
hiperparametros del notebook original:

    predictor_type = 'regressor'   -> perdida cuadratica (squared_loss)
    num_models     = 16            -> entrena 16 modelos y se queda con el mejor
    feature_dim    = 16            -> 16 columnas de entrada

y con los valores por defecto que documenta AWS:

    optimizer        = 'adam'
    mini_batch_size  = 1000
    normalize_data   = True        -> normaliza las features
    normalize_label  = True        -> normaliza el precio (regresion)
    loss             = 'squared_loss'

Referencia: https://docs.aws.amazon.com/sagemaker/latest/dg/ll_hyperparameters.html
"""

import numpy as np

MINI_BATCH_SIZE = 1000
EPOCAS = 200          # AWS usa 15 por defecto; subimos para converger igual de bien en CPU
BETA1, BETA2, EPS = 0.9, 0.999, 1e-8


def _adam(X, y, learning_rate, wd, epocas, mini_batch_size, semilla):
    """Un solo modelo lineal entrenado con Adam sobre mini-batches (datos ya normalizados)."""
    rng = np.random.default_rng(semilla)
    n, d = X.shape

    w = np.zeros(d)          # pesos
    b = 0.0                  # sesgo (intercept)
    mw, vw = np.zeros(d), np.zeros(d)
    mb, vb = 0.0, 0.0
    t = 0

    for _ in range(epocas):
        orden = rng.permutation(n)
        for inicio in range(0, n, mini_batch_size):
            idx = orden[inicio:inicio + mini_batch_size]
            Xb, yb = X[idx], y[idx]
            m = len(idx)

            # gradiente de la perdida cuadratica + regularizacion L2 (wd)
            error = Xb @ w + b - yb
            gw = (2.0 / m) * (Xb.T @ error) + 2.0 * wd * w
            gb = (2.0 / m) * error.sum()

            t += 1
            mw = BETA1 * mw + (1 - BETA1) * gw
            vw = BETA2 * vw + (1 - BETA2) * gw ** 2
            mb = BETA1 * mb + (1 - BETA1) * gb
            vb = BETA2 * vb + (1 - BETA2) * gb ** 2

            # correccion de sesgo de Adam
            mw_c, vw_c = mw / (1 - BETA1 ** t), vw / (1 - BETA2 ** t)
            mb_c, vb_c = mb / (1 - BETA1 ** t), vb / (1 - BETA2 ** t)

            w -= learning_rate * mw_c / (np.sqrt(vw_c) + EPS)
            b -= learning_rate * mb_c / (np.sqrt(vb_c) + EPS)

    return w, b


def rejilla_de_modelos(num_models=16):
    """Las `num_models` combinaciones (learning_rate, weight_decay) que se van a competir."""
    tasas = [0.001, 0.005, 0.01, 0.05]
    decays = [0.0, 1e-6, 1e-4, 1e-2]
    combos = [(lr, wd) for lr in tasas for wd in decays]
    return combos[:num_models]


def entrenar(X_entrenamiento, y_entrenamiento, num_models=16,
             epocas=EPOCAS, mini_batch_size=MINI_BATCH_SIZE,
             fraccion_validacion=0.2, semilla=0, verbose=True):
    """
    Entrena `num_models` modelos lineales y devuelve el mejor.

    Devuelve un diccionario de arrays de NumPy (NO un objeto de sklearn) para que
    el artefacto sea independiente de versiones de librerias al servirlo.
    """
    X = np.asarray(X_entrenamiento, dtype=np.float64)
    y = np.asarray(y_entrenamiento, dtype=np.float64).ravel()

    # --- separamos una particion interna de validacion para elegir el mejor modelo
    rng = np.random.default_rng(semilla)
    orden = rng.permutation(len(X))
    corte = int(len(X) * (1 - fraccion_validacion))
    tr, va = orden[:corte], orden[corte:]
    X_tr, y_tr, X_va, y_va = X[tr], y[tr], X[va], y[va]

    # --- normalize_data=True / normalize_label=True (estadisticas SOLO de entrenamiento)
    x_mean, x_std = X_tr.mean(axis=0), X_tr.std(axis=0)
    x_std[x_std == 0] = 1.0
    y_mean, y_std = y_tr.mean(), y_tr.std()

    X_tr_n, X_va_n = (X_tr - x_mean) / x_std, (X_va - x_mean) / x_std
    y_tr_n, y_va_n = (y_tr - y_mean) / y_std, (y_va - y_mean) / y_std

    # --- competencia de num_models modelos
    resultados = []
    for i, (lr, wd) in enumerate(rejilla_de_modelos(num_models), start=1):
        w, b = _adam(X_tr_n, y_tr_n, lr, wd, epocas, mini_batch_size, semilla + i)
        mse_val = float(np.mean((X_va_n @ w + b - y_va_n) ** 2))
        resultados.append({"lr": lr, "wd": wd, "mse_val": mse_val, "w": w, "b": b})
        if verbose:
            print(f"  modelo {i:2d}/{num_models}  learning_rate={lr:<6g} wd={wd:<8g} "
                  f"-> MSE validacion (normalizado) = {mse_val:.6f}")

    mejor = min(resultados, key=lambda r: r["mse_val"])
    if verbose:
        print(f"\n  >>> Gana learning_rate={mejor['lr']}, wd={mejor['wd']} "
              f"(MSE={mejor['mse_val']:.6f})")

    return {
        "coef": mejor["w"],
        "intercept": float(mejor["b"]),
        "x_mean": x_mean,
        "x_std": x_std,
        "y_mean": float(y_mean),
        "y_std": float(y_std),
        "hiperparametros": {"learning_rate": mejor["lr"], "wd": mejor["wd"],
                            "epocas": epocas, "mini_batch_size": mini_batch_size,
                            "num_models": num_models},
        "resultados_competencia": [{k: v for k, v in r.items() if k not in ("w", "b")}
                                   for r in resultados],
    }


def predecir(modelo, X):
    """Misma matematica que usa el endpoint (ver code/inference.py)."""
    X = np.asarray(X, dtype=np.float64)
    if X.ndim == 1:
        X = X.reshape(1, -1)
    X_n = (X - modelo["x_mean"]) / modelo["x_std"]
    return (X_n @ modelo["coef"] + modelo["intercept"]) * modelo["y_std"] + modelo["y_mean"]


def metricas(y_real, y_pred):
    y_real, y_pred = np.ravel(y_real), np.ravel(y_pred)
    residuo = y_real - y_pred
    ss_res = float(np.sum(residuo ** 2))
    ss_tot = float(np.sum((y_real - y_real.mean()) ** 2))
    return {
        "RMSE": float(np.sqrt(np.mean(residuo ** 2))),
        "MAE": float(np.mean(np.abs(residuo))),
        "R2": 1.0 - ss_res / ss_tot,
    }


def coeficientes_en_crudo(modelo, nombres=None):
    """
    Convierte los pesos del espacio normalizado al espacio original (dolares por unidad).
    Sirve para interpretar el modelo: cuanto suma al precio cada pie cuadrado, cada baño, etc.
    """
    coef_crudo = modelo["coef"] * modelo["y_std"] / modelo["x_std"]
    intercepto_crudo = (modelo["y_mean"] + modelo["y_std"] * modelo["intercept"]
                        - float(np.sum(coef_crudo * modelo["x_mean"])))
    if nombres is None:
        return coef_crudo, intercepto_crudo
    return dict(zip(nombres, coef_crudo)), intercepto_crudo
