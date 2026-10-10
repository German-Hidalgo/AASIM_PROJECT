# =====================================================================
# FASE 3 | Orquestador de los bloques 1-8 (AASIM)
# ---------------------------------------------------------------------
# Ejecuta la cadena completa del modelado sobre la ABT versionada y
# guarda cada resultado (CSV/JSON/PNG) en ``results/modeling/fase3``.
#  1  config           -> config_fase3.json, semilla fijada
#  2  data_access      -> inventario_pacientes.json
#  3  pipeline + QC    -> pipeline_fase3.json, informe_qc.json, hist
#  4  ABT versionada   -> verifica el manifiesto (abt.py, ya sellado)
#  5  no-fuga/balance  -> no_fuga_y_balance.json
#  6  baselines+fuga   -> baselines.csv, pruebas_fuga.json
#  7  avanzados        -> avanzados.csv, tuning.json, ablation.csv
#  8  clasificación    -> clasificacion.json, matriz de confusión
#  T  trazabilidad     -> experimentos.jsonl (append-only)
# Este orquestador NO toca la partición ``test``.
# Responsable: Rocha (ingeniería TI).
# =====================================================================

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from src.modeling import advanced as adv
from src.modeling import baselines as base
from src.modeling import classification as clasif
from src.modeling import leakage_checks as nofuga
from src.modeling import pipeline as pipe
from src.modeling import tracking as trk
from src.modeling import tuning as tun
from src.modeling.abt import cargar_abt
from src.modeling.config import (
    SEMILLA_DEFAULT,
    ConfigFase3,
    fijar_semillas,
    guardar_config,
)
from src.modeling.data_access import listado_pacientes, resumen_caché
from src.modeling.validation import con_early_stopping

BLOQUES: list[tuple[int, str]] = [
    (1, "configuración"),
    (2, "acceso y caché"),
    (3, "preproceso, QC y ABT"),
    (4, "ABT versionada"),
    (5, "no-fuga y balance"),
    (6, "baselines y fuga"),
    (7, "avanzados, tuning y ablación"),
    (8, "clasificación"),
]


def _escribir(cfg: ConfigFase3, nombre: str, payload) -> Path:
    ruta = cfg.out_base / nombre
    if isinstance(payload, (dict, list)):
        ruta.write_text(
            json.dumps(
                payload, indent=2, ensure_ascii=False, default=str, sort_keys=True
            ),
            encoding="utf-8",
        )
    else:
        ruta.write_text(str(payload), encoding="utf-8")
    return ruta


def _todo(cfg: ConfigFase3, solo: set[int] | None = None) -> None:
    deps = {1, 2, 3, 4, 5, 6, 7, 8}
    seleccion = deps if solo is None else (solo & deps)
    fijar_semillas(cfg.semilla)
    cfg.preparar_salidas()

    # Bloque 1: configuración central + semilla.
    if 1 in seleccion:
        t0 = time.time()
        ruta = guardar_config(cfg, cfg.out_base / "config_fase3.json")
        print(
            f"[bloque 1/8] configuración guardada en {ruta} ({time.time() - t0:.1f}s)",
            flush=True,
        )

    # Bloque 2: acceso y caché (ABT validada por SHA-256).
    if 2 in seleccion:
        t0 = time.time()
        abt_v = cargar_abt(cfg.abt_dir)
        pac = listado_pacientes(abt_v)
        cache = resumen_caché(abt_v)
        _escribir(
            cfg,
            "inventario_pacientes.json",
            {"cache": cache, "pacientes": pac.to_dict(orient="records")},
        )
        print(
            f"[bloque 2/8] ABT {abt_v.shape} · {cache['n_pacientes']} pacientes · "
            f"{cache['n_ventanas']} ventanas ({time.time() - t0:.1f}s)",
            flush=True,
        )

    abt = cargar_abt(cfg.abt_dir)

    # Bloque 3: pipeline de preproceso + QC (solo train).
    if 3 in seleccion:
        t0 = time.time()
        train = abt[abt["split"] == "train"]
        features = tuple(sorted(c for c in abt.columns if c.startswith("feat_")))
        pl1 = pipe.construir_pipeline(features)
        pl1 = pipe.ajustar(pl1, train[list(features)].assign(_subj=train["subject_id"]))
        pipe.guardar_pipeline(pl1, cfg.out_base / "pipeline_fase3.json")
        qc = pipe.informe_qc(abt, cfg.target)
        _escribir(cfg, "informe_qc.json", qc)
        print(
            f"[bloque 3/8] pipeline guardado, QC: SBP "
            f"{qc['describe_target'].get('mean'):.1f}±{qc['describe_target'].get('std'):.1f} "
            f"({time.time() - t0:.1f}s)",
            flush=True,
        )

    # Bloque 4: ABT versionada (manifiesto ya validado por cargar_abt).
    if 4 in seleccion:
        t0 = time.time()
        manif = json.loads(
            (cfg.abt_dir / "abt_manifest.json").read_text(encoding="utf-8")
        )
        print(
            f"[bloque 4/8] ABT v{manif['version']} · sha256 "
            f"{manif['sha256'][:16]}… · splits {manif['conteos_por_split']} "
            f"({time.time() - t0:.1f}s)",
            flush=True,
        )

    # Bloque 5: evidencia de no-fuga y balance.
    if 5 in seleccion:
        t0 = time.time()
        cert = cfg.particion_dir / "certificado_patient_wise.json"
        if not cert.exists():
            cert = (
                Path("data/processed/pulsedb_particion")
                / "certificado_patient_wise.json"
            )
        informe = nofuga.generar_informe(abt, cert, cfg.target)
        _escribir(cfg, "no_fuga_y_balance.json", informe)
        ok = informe["no_fuga"]["intersecciones_ok"]
        print(
            f"[bloque 5/8] intersecciones OK={ok} · "
            f"resto advertencias={len(informe['advertencias_fuga_objetivo'])} "
            f"({time.time() - t0:.1f}s)",
            flush=True,
        )

    # Bloque 6: baselines + pruebas de fuga (regresión y clasificación).
    if 6 in seleccion:
        t0 = time.time()
        res = base.entrenar_baselines(abt, cfg.target, "regresion", semilla=cfg.semilla)
        pd_result = _resultados_df(res)
        pd_result.to_csv(cfg.out_base / "baselines.csv", index=False)
        fuga = base.pruebas_fuga_modelo(abt, cfg.target, semilla=cfg.semilla)
        _escribir(cfg, "pruebas_fuga.json", fuga)
        print(
            f"[bloque 6/8] baselines: "
            f"MAE=Dummy {pd_result['valor'].iloc[0]:.2f} / "
            f"Ridge {pd_result['valor'].iloc[1]:.2f} / "
            f"SVR {pd_result['valor'].iloc[2]:.2f} · "
            f"sujeto {fuga['mae_rf_split_sujeto']:.2f} vs aleatorio "
            f"{fuga['mae_rf_split_aleatorio']:.2f} vs shuffle "
            f"{fuga['mae_rf_label_shuffle']:.2f} ({time.time() - t0:.1f}s)",
            flush=True,
        )

    # Bloque 7: avanzados + early stopping + tuning + ablación.
    if 7 in seleccion:
        t0 = time.time()
        res_a = adv.entrenar_avanzados(
            abt, cfg.target, "regresion", semilla=cfg.semilla
        )
        df_a = _resultados_df(res_a, {"semilla": cfg.semilla})
        df_a.to_csv(cfg.out_base / "avanzados.csv", index=False)
        try:
            es = con_early_stopping(abt, cfg.target, "regresion", semilla=cfg.semilla)
            _escribir(cfg, "early_stopping.json", es)
            print(f"[bloque 7/8] early stopping: {es['n_arboles_elegidos']} árboles")
        except RuntimeError as exc:
            print(f"[bloque 7/8] early stopping no disponible: {exc}")
        # Tuning (Optuna) con CV agrupada por sujeto: alpha de Ridge (regresión).
        try:
            espacio = {"alpha": (1e-3, 1e3)}
            tuni = tun.buscar_hiperparametros(
                abt,
                cfg.target,
                "regresion",
                espacio,
                n_splits=3,
                semilla=cfg.semilla,
                n_trials=8,
            )
            _escribir(cfg, "tuning.json", tuni)
            print(
                f"[bloque 7/8] tuning: alpha={tuni['mejores_params'].get('alpha'):.3g} "
                f"MAE={tuni['mejor_valor']:.2f}"
            )
        except Exception as exc:  # noqa: BLE001 - el tuning no debe romper el bloque
            print(f"[bloque 7/8] tuning no disponible: {exc}")
        abl = tun.ablation_features(abt, cfg.target, "regresion", semilla=cfg.semilla)
        abl.to_csv(cfg.out_base / "ablation.csv", index=False)
        print(
            f"[bloque 7/8] avanzados + ablación ({time.time() - t0:.1f}s)", flush=True
        )

    # Bloque 8: clasificación derivada de la PAS.
    if 8 in seleccion:
        t0 = time.time()
        res_cl = clasif.evaluar_clasificadores(abt, cfg.target, semilla=cfg.semilla)
        _escribir(cfg, "clasificacion.json", res_cl)
        print(
            f"[bloque 8/8] clasificación: {[m['macro_f1'] for m in res_cl['tabla_modelos']]} "
            f"({time.time() - t0:.1f}s)",
            flush=True,
        )

    # Trazabilidad: consolidar log append-only.
    df_log = trk.leer_registros(cfg.log_dir)
    print(f"[tracking] {len(df_log)} registro(s) en el log", flush=True)

    # Figuras de evidencia (a partir de lo ya guardado; nunca tocan test).
    if seleccion & {6, 7, 8}:
        _generar_figuras(cfg)


def _generar_figuras(cfg: ConfigFase3) -> None:
    """Regenera los PNG de evidencia a partir de los CSV/JSON guardados."""
    import json

    import numpy as np
    import pandas as pd

    from src.modeling import plots
    from src.modeling.config import CLASES_SBP_NOMBRES

    try:
        abt = cargar_abt(cfg.abt_dir)
        ruta = plots.histogramas_por_fold(abt, cfg.target, cfg)
        print(f"[figuras] {ruta.name}", flush=True)
    except Exception as exc:  # noqa: BLE001 - las figuras no rompen la corrida
        print(f"[figuras] histogramas_por_fold no disponible: {exc}", flush=True)

    dfs: list[pd.DataFrame] = []
    for nombre in ("baselines.csv", "avanzados.csv"):
        ruta = cfg.out_base / nombre
        if ruta.exists():
            dfs.append(pd.read_csv(ruta))
    if dfs:
        try:
            exp = pd.concat(dfs, ignore_index=True)
            ruta = plots.barras_mae(exp, cfg)
            print(f"[figuras] {ruta.name}", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[figuras] barras_mae no disponible: {exc}", flush=True)

    if (cfg.out_base / "ablation.csv").exists():
        try:
            ruta = plots.barras_ablation(
                pd.read_csv(cfg.out_base / "ablation.csv"), cfg
            )
            print(f"[figuras] {ruta.name}", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[figuras] ablation no disponible: {exc}", flush=True)

    if (cfg.out_base / "clasificacion.json").exists():
        try:
            cl = json.loads(
                (cfg.out_base / "clasificacion.json").read_text(encoding="utf-8")
            )
            tabla = cl["tabla_modelos"]
            mejor = max(tabla, key=lambda m: m["macro_f1"])["modelo"]
            matriz = cl["matrices"][mejor]
            ruta = plots.matriz_confusion(
                np.array(matriz), list(CLASES_SBP_NOMBRES), cfg
            )
            print(f"[figuras] {ruta.name} ({mejor})", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[figuras] matriz_confusion no disponible: {exc}", flush=True)


def _resultados_df(resultados: list, extra: dict | None = None):
    import pandas as pd

    filas = []
    for r in resultados:
        fila = {
            "modelo": r.nombre,
            "tarea": r.tarea,
            "metrica_principal": r.metrica_principal,
            "valor": r.valor,
            **r.metricas,
            "n_train": r.n_train,
            "n_val": r.n_val,
            "semilla": r.semilla,
            **(extra or {}),
        }
        filas.append(fila)
    return pd.DataFrame(filas)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="FASE 3 - orquestador de bloques 1-8")
    p.add_argument("--abt-dir", type=Path, default=None)
    p.add_argument("--semilla", type=int, default=SEMILLA_DEFAULT)
    p.add_argument(
        "--solo", type=str, default="", help="p. ej. '3,4' para solo esos bloques"
    )
    args = p.parse_args(argv)

    cfg = ConfigFase3(semilla=args.semilla)
    if args.abt_dir:
        cfg = ConfigFase3(semilla=args.semilla, abt_dir=args.abt_dir)

    solo: set[int] | None = None
    if args.solo.strip():
        try:
            solo = {int(x) for x in args.solo.split(",") if x.strip()}
        except ValueError as exc:
            raise SystemExit(f"--solo debe ser lista de enteros: {args.solo}") from exc

    t_inicio = time.time()
    _todo(cfg, solo=solo)
    print(f"\n== FASE 3 lista ({(time.time() - t_inicio):.1f}s) ==", flush=True)
    print(f"Resultados en: {cfg.out_base}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
