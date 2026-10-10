# =====================================================================
# FASE 3 | Bloque 7a: Modelos avanzados (AASIM)
# ---------------------------------------------------------------------
# Modelos de mayor capacidad comparados bajo el MISMO esquema de CV por
# sujeto que los baselines:
#   * Random Forest (sklearn);
#   * LightGBM (con early stopping agrupado por sujeto opcional);
#   * MLP (torch) con aceleración GPU (CUDA) si está disponible.
# Toda métrica se calcula con ``src.modeling.validation`` y se guarda en
# CSV/JSON por experimento.
# Responsable: Rocha (ingeniería TI); revisión clínica: Buitrago.
# =====================================================================

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.modeling.baselines import SEMILLA_DEFAULT, ResultadoModelo
from src.modeling.config import ConfigFase3


# --------------------------------------------------------------------------
# MLP con PyTorch (GPU si está disponible)
# --------------------------------------------------------------------------
@dataclass
class MlpTorch:
    """MLP compacto de 2 capas ocultas para regresión o clasificación.

    Usa CUDA cuando ``torch.cuda.is_available()``; de lo contrario CPU.
    Pensado para volúmenes pequeños (20-40 sujetos, cientos de ventanas):
    entrena en épocas cortas y con parada temprana.
    """

    capas: tuple[int, ...] = (64, 32)
    epocas: int = 60
    lote: int = 32
    lr: float = 1e-3
    peso_decay: float = 1e-4
    semilla: int = SEMILLA_DEFAULT

    def _dispositivo(self) -> str:
        try:
            import torch

            return "cuda" if torch.cuda.is_available() else "cpu"
        except Exception:  # pragma: no cover - torch ausente  # noqa: BLE001
            return "cpu"

    def __post_init__(self) -> None:
        self._dev = self._dispositivo()
        self._cls = None  # clases de clasificación (si aplica)

    def _red(self, n_entrada: int, n_salida: int):
        from torch import nn

        dims = [n_entrada, *self.capas, n_salida]
        mods: list[nn.Module] = []
        for i in range(len(dims) - 2):
            mods.append(nn.Linear(dims[i], dims[i + 1]))
            mods.append(nn.ReLU())
        mods.append(nn.Linear(dims[-2], dims[-1]))
        return nn.Sequential(*mods)

    def fit(self, X: np.ndarray, y: Any) -> MlpTorch:
        import torch
        from torch import nn

        X = np.asarray(X, dtype=np.float32)
        if isinstance(y, pd.Series):
            y_vals = y.to_numpy()
        else:
            y_vals = np.asarray(y)
        if y_vals.dtype.kind in "iuf":
            probs = False  # regresión continua
        else:
            self._cls = np.unique(y_vals)
            probs = True

        if probs:
            y_cod = np.searchsorted(self._cls, y_vals).astype(np.int64)
            n_salida = len(self._cls)
            perdida = nn.CrossEntropyLoss()
        else:
            y_cod = y_vals.astype(np.float32).reshape(-1, 1)
            n_salida = 1
            perdida = nn.MSELoss()

        torch.manual_seed(self.semilla)
        red = self._red(int(X.shape[1]), n_salida).to(self._dev)
        opt = torch.optim.Adam(
            red.parameters(), lr=self.lr, weight_decay=self.peso_decay
        )

        Xt = torch.tensor(X, device=self._dev)
        yt = torch.tensor(y_cod, device=self._dev)
        n = len(Xt)
        for _ in range(self.epocas):
            red.train()
            perm = torch.randperm(n, device=self._dev)
            for i in range(0, n, self.lote):
                idx = perm[i : i + self.lote]
                opt.zero_grad()
                out = red(Xt[idx])
                loss = perdida(out, yt[idx])
                loss.backward()
                opt.step()
        self._red_ = red
        self._probs_ = probs
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        import torch

        red = self._red_.to(self._dev).eval()
        Xt = torch.tensor(np.asarray(X, dtype=np.float32), device=self._dev)
        with torch.no_grad():
            out = red(Xt).cpu().numpy()
        if self._probs_:
            return self._cls[np.argmax(out, axis=1)]
        return out.ravel()


# --------------------------------------------------------------------------
# Catálogo de modelos avanzados
# --------------------------------------------------------------------------
def modelos_avanzados(
    tarea: str, usar_mlp: bool = True, semilla: int = SEMILLA_DEFAULT
) -> dict[str, Any]:
    """Devuelve los estimadores avanzados (callables) sin entrenar.

    Returns:
        Dict ``nombre -> fabrica`` donde ``fabrica()`` construye un
        estimador listo para ``fit/predict``.
    """
    from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor

    try:
        from lightgbm import LGBMClassifier, LGBMRegressor

        _LGB = True
    except ImportError:  # pragma: no cover - dependencia opcional
        _LGB = False

    def _rf() -> Any:
        if tarea == "regresion":
            return RandomForestRegressor(
                n_estimators=200, random_state=semilla, n_jobs=-1
            )
        return RandomForestClassifier(n_estimators=200, random_state=semilla, n_jobs=-1)

    modelos: dict[str, Any] = {"RandomForest": _rf}

    if _LGB:

        def _lgb() -> Any:
            if tarea == "regresion":
                return LGBMRegressor(
                    n_estimators=200, random_state=semilla, n_jobs=-1, verbosity=-1
                )
            return LGBMClassifier(
                n_estimators=200, random_state=semilla, n_jobs=-1, verbosity=-1
            )

        modelos["LightGBM"] = _lgb

    if usar_mlp:

        def _mlp() -> MlpTorch:
            return MlpTorch(semilla=semilla)

        modelos["MLP_torch"] = _mlp
    return modelos


def entrenar_avanzados(
    abt: pd.DataFrame,
    target: str,
    tarea: str,
    semilla: int = SEMILLA_DEFAULT,
    usar_mlp: bool = True,
) -> list[ResultadoModelo]:
    """Entrena y evalúa los modelos avanzados con CV agrupada por sujeto.

    Se reutiliza ``src.modeling.validation.validacion_agrupada`` con el
    mismo esquema y semilla de los baselines para que las tablas sean
    comparables. Cada pliegue imputa/escala con estadísticos solo de ese
    subentrenamiento (evita fuga intra-CV).

    Returns:
        Lista de ``ResultadoModelo`` con métricas promedio sobre pliegues.
    """
    from src.modeling.validation import (
        validacion_agrupada,
    )

    modelos = modelos_avanzados(tarea, usar_mlp=usar_mlp, semilla=semilla)
    resultados: list[ResultadoModelo] = []

    # Para clasificación se usa el target de clase derivado (3 estratos).
    from src.modeling.baselines import preparar_target

    abt_uso, target_uso = preparar_target(abt, target, tarea)
    principal = "mae" if tarea == "regresion" else "macro_f1"

    for nombre, fabrica in modelos.items():
        try:
            tabla = validacion_agrupada(
                abt_uso,
                target_uso,
                tarea,
                n_splits=5,
                semilla=semilla,
                modelo=fabrica,
            )
        except Exception as exc:  # pragma: no cover - dejar rastro  # noqa: BLE001
            print(f"[advanced] {nombre} falló: {exc}")
            continue
        if tabla.empty:
            continue
        promedio = (
            tabla[principal].mean() if principal in tabla.columns else float("nan")
        )
        metricas = {
            k: (float(tabla[k].mean()) if k in tabla.columns else float("nan"))
            for k in (
                ("mae", "rmse", "me", "sd_error", "r_pearson", "bhs_5", "aami_strato14")
                if tarea == "regresion"
                else ("balanced_accuracy", "macro_f1")
            )
        }
        resultados.append(
            ResultadoModelo(
                nombre=nombre,
                tarea=tarea,
                metrica_principal=principal,
                valor=float(promedio),
                metricas=metricas,
                n_train=int(sum(tabla["n_val"])),
                n_val=(len(abt[abt["split"] == "train"])),
                params={"n_splits": 5, "semilla": semilla},
                semilla=semilla,
            )
        )
    return resultados


def main(argv: list[str] | None = None) -> int:
    """CLI: entrena avanzados y guarda CSV/JSON con métricas por modelo."""
    p = argparse.ArgumentParser(description="FASE 3 - Bloque 7a: modelos avanzados")
    p.add_argument("--abt-dir", type=Path, default=None)
    p.add_argument("--target", type=str, default="sbp_mmhg")
    p.add_argument(
        "--tarea", choices=("regresion", "clasificacion"), default="regresion"
    )
    p.add_argument("--semilla", type=int, default=SEMILLA_DEFAULT)
    p.add_argument("--no-mlp", action="store_true", help="Desactiva el MLP (torch)")
    args = p.parse_args(argv)

    import os

    from src.modeling.data_access import cargar_datos

    os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
    cfg = ConfigFase3(abt_dir=args.abt_dir or ConfigFase3().abt_dir)
    cfg.preparar_salidas()
    abt = cargar_datos(cfg)

    resultados = entrenar_avanzados(
        abt, args.target, args.tarea, semilla=args.semilla, usar_mlp=not args.no_mlp
    )
    filas = [
        {
            "nombre": r.nombre,
            "tarea": r.tarea,
            "metrica_principal": r.metrica_principal,
            "valor": r.valor,
            **r.metricas,
            "semilla": r.semilla,
        }
        for r in resultados
    ]
    df = pd.DataFrame(filas)
    print(df.to_string(index=False))
    salida = cfg.out_base / "avanzados.csv"
    df.to_csv(salida, index=False)
    print(f"[advanced] guardado en {salida}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
