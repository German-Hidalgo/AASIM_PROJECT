# =====================================================================
# FASE 3 | Figuras de evidencia (AASIM)
# ---------------------------------------------------------------------
# Genera los gráficos que acompañan los entregables de los bloques 5-8:
# histogramas por fold, barras de MAE con SD, Bland-Altman, errores por
# sujeto, barras de ablación, matriz de confusión normalizada y curva de
# early stopping. Todas las figuras se guardan en
# ``results/modeling/fase3/figuras``.
# Responsable: Rocha (ingeniería TI).
# =====================================================================

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from src.modeling.config import CLASES_SBP_NOMBRES, ConfigFase3

_ESTILOS = {
    "figure.figsize": (9, 5),
    "figure.dpi": 120,
    "font.size": 10,
    "axes.grid": True,
    "grid.alpha": 0.3,
}
for k, v in _ESTILOS.items():
    plt.rcParams[k] = v


def _guardar(fig: plt.Figure, cfg: ConfigFase3, nombre: str) -> Path:
    cfg.figura_dir.mkdir(parents=True, exist_ok=True)
    ruta = cfg.figura_dir / nombre
    fig.tight_layout()
    fig.savefig(ruta, bbox_inches="tight")
    plt.close(fig)
    return ruta


def histogramas_por_fold(
    abt: pd.DataFrame,
    target: str,
    cfg: ConfigFase3,
    n_splits: int = 5,
    semilla: int = 20260920,
) -> Path:
    """Histogramas superpuestos de la PAS por pliegue (validación agrupada)."""
    from src.modeling.validation import esquema_cv

    fig, ax = plt.subplots()
    pliegues = esquema_cv(abt, n_splits=n_splits, semilla=semilla, sobre="train")
    for fold in pliegues:
        mask = abt["subject_id"].astype(str).isin(fold.sujetos_val)
        ax.hist(
            abt.loc[mask, target].dropna(),
            bins=20,
            alpha=0.45,
            label=f"fold {fold.indice}",
        )
    ax.set_xlabel(f"{target} (mmHg)")
    ax.set_ylabel("ventanas")
    ax.set_title("Distribución de la PAS por pliegue (CV por sujeto)")
    ax.legend(fontsize=8)
    return _guardar(fig, cfg, "histogramas_por_fold.png")


def barras_mae(df_experimentos: pd.DataFrame, cfg: ConfigFase3) -> Path:
    """Barras de MAE por modelo con barras de error (±SD entre folds)."""
    if "mae" not in df_experimentos.columns or "modelo" not in df_experimentos.columns:
        raise ValueError("Se esperan columnas 'modelo' y 'mae'")
    fig, ax = plt.subplots()
    agg = (
        df_experimentos.groupby("modelo")["mae"]
        .agg(["mean", "std"])
        .reindex(df_experimentos.groupby("modelo")["mae"].mean().sort_values().index)
    )
    ax.bar(
        agg.index,
        agg["mean"],
        yerr=agg["std"].fillna(0),
        capsize=4,
        color="steelblue",
    )
    ax.set_ylabel("MAE (mmHg)")
    ax.set_title("MAE por modelo (CV agrupada por sujeto)")
    ax.tick_params(axis="x", rotation=30)
    return _guardar(fig, cfg, "mae_por_modelo.png")


def bland_altman(
    y_real: np.ndarray,
    y_pred: np.ndarray,
    cfg: ConfigFase3,
    nombre: str = "bland_altman.png",
) -> Path:
    """Gráfico de Bland-Altman: promedio vs diferencia ±1.96σ."""
    y_real = np.asarray(y_real, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    ok = np.isfinite(y_real) & np.isfinite(y_pred)
    y_real, y_pred = y_real[ok], y_pred[ok]
    prom = (y_real + y_pred) / 2
    dif = y_pred - y_real
    media, sd = np.mean(dif), np.std(dif, ddof=1)
    fig, ax = plt.subplots()
    ax.scatter(prom, dif, alpha=0.4, s=14)
    ax.axhline(media, color="tab:red", ls="--", label=f"sesgo {media:.1f}")
    ax.axhline(
        media + 1.96 * sd,
        color="tab:orange",
        ls=":",
        label=f"+1.96σ {media + 1.96 * sd:.1f}",
    )
    ax.axhline(
        media - 1.96 * sd,
        color="tab:orange",
        ls=":",
        label=f"−1.96σ {media - 1.96 * sd:.1f}",
    )
    ax.set_xlabel("(real + predicho)/2 (mmHg)")
    ax.set_ylabel("predicho − real (mmHg)")
    ax.set_title("Bland-Altman (PAS)")
    ax.legend(fontsize=8)
    return _guardar(fig, cfg, nombre)


def errores_por_sujeto(abt: pd.DataFrame, y_pred: np.ndarray, cfg: ConfigFase3) -> Path:
    """Boxplot del error (pred - real) por sujeto en la partición val."""
    val = abt[abt["split"] == "val"]
    err = np.asarray(y_pred, dtype=float) - val["sbp_mmhg"].to_numpy(dtype=float)
    tabla = pd.DataFrame({"subject_id": val["subject_id"].astype(str), "error": err})
    fig, ax = plt.subplots()
    tabla.boxplot(column="error", by="subject_id", ax=ax, rot=45, fontsize=7)
    ax.set_title("Error por sujeto (val)")
    ax.set_xlabel("sujeto")
    ax.set_ylabel("pred − real (mmHg)")
    plt.suptitle("")
    return _guardar(fig, cfg, "error_por_sujeto.png")


def barras_ablation(df_ablation: pd.DataFrame, cfg: ConfigFase3) -> Path:
    """Barras de ablación: MAE por configuración (todas / sin_<grupo>)."""
    if df_ablation.empty or "mae" not in df_ablation.columns:
        raise ValueError("DF de ablación vacío o sin 'mae'")
    fig, ax = plt.subplots()
    orden = df_ablation.sort_values("mae")
    ax.bar(orden["config"], orden["mae"], color="indianred")
    ax.set_ylabel("MAE (mmHg)")
    ax.set_title("Ablación de grupos de features (MAE)")
    ax.tick_params(axis="x", rotation=35)
    return _guardar(fig, cfg, "ablation.png")


def matriz_confusion(matriz: np.ndarray, clases: list[str], cfg: ConfigFase3) -> Path:
    """Matriz de confusión normalizada por fila (recall por clase)."""
    fig, ax = plt.subplots()
    m = np.asarray(matriz, dtype=float)
    norm = m / m.sum(axis=1, keepdims=True)
    im = ax.imshow(norm, cmap="Blues")
    fig.colorbar(im, ax=ax, fraction=0.046)
    ax.set_xticks(range(len(clases)), clases, rotation=30)
    ax.set_yticks(range(len(clases)), clases)
    for i in range(norm.shape[0]):
        for j in range(norm.shape[1]):
            ax.text(
                j,
                i,
                f"{norm[i, j]:.2f}",
                ha="center",
                va="center",
                color="white" if norm[i, j] > 0.5 else "black",
            )
    ax.set_xlabel("predicho")
    ax.set_ylabel("real")
    ax.set_title("Matriz de confusión normalizada (clasificación 3 clases)")
    return _guardar(fig, cfg, "matriz_confusion.png")


def curva_early_stopping(
    historial: np.ndarray, cfg: ConfigFase3, nombre: str = "early_stopping.png"
) -> Path:
    """Curva de error de entrenamiento vs early-stop (historial de LightGBM)."""
    fig, ax = plt.subplots()
    for serie, etiqueta in zip(
        historial, ("entrenamiento", "validación"), strict=False
    ):
        ax.plot(serie, label=etiqueta)
    ax.set_xlabel("iteración (árboles)")
    ax.set_ylabel("MAE (mmHg)")
    ax.set_title("Early stopping por sujeto (early_stopping)")
    ax.legend()
    return _guardar(fig, cfg, nombre)


def generar_todas(
    abt: pd.DataFrame,
    df_cv: pd.DataFrame,
    df_experimentos: pd.DataFrame,
    df_ablation: pd.DataFrame,
    matriz: np.ndarray | None = None,
    cfg: ConfigFase3 | None = None,
) -> list[Path]:
    """Genera el set de figuras estándar de la Fase 3 (devolvidas en orden)."""
    cfg = cfg or ConfigFase3()
    rutas: list[Path] = []
    rutas.append(histogramas_por_fold(abt, cfg.target, cfg))
    if not df_experimentos.empty:
        try:
            rutas.append(barras_mae(df_experimentos, cfg))
        except Exception:  # pragma: no cover  # noqa: BLE001, S110
            pass
    if not df_ablation.empty:
        try:
            rutas.append(barras_ablation(df_ablation, cfg))
        except Exception:  # pragma: no cover  # noqa: BLE001, S110
            pass
    if matriz is not None:
        try:
            rutas.append(matriz_confusion(matriz, list(CLASES_SBP_NOMBRES), cfg))
        except Exception:  # pragma: no cover  # noqa: BLE001, S110
            pass
    return rutas


def main(argv: list[str] | None = None) -> int:
    """CLI: genera las figuras a partir de los CSV guardados por los bloques."""
    import argparse

    p = argparse.ArgumentParser(description="FASE 3 - figuras de evidencia")
    p.add_argument("--abt-dir", type=Path, default=None)
    args = p.parse_args(argv)

    from src.modeling.data_access import cargar_datos

    cfg = ConfigFase3(abt_dir=args.abt_dir or ConfigFase3().abt_dir)
    cfg.preparar_salidas()
    abt = cargar_datos(cfg)

    df_exp = (
        pd.read_csv(cfg.out_base / "baselines.csv")
        if (cfg.out_base / "baselines.csv").exists()
        else pd.DataFrame()
    )
    df_abl = (
        pd.read_csv(cfg.out_base / "ablation.csv")
        if (cfg.out_base / "ablation.csv").exists()
        else pd.DataFrame()
    )

    rutas = histogramas_por_fold(abt, cfg.target, cfg)
    print(f"[plots] guardada {rutas}")
    if not df_exp.empty:
        print(f"[plots] guardada {barras_mae(df_exp, cfg)}")
    if not df_abl.empty:
        print(f"[plots] guardada {barras_ablation(df_abl, cfg)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
