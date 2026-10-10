# Data Quality Report (DQR) - Fase 2 del Sistema AASIM

**Proyecto:** AASIM - Software como Dispositivo Médico (SaMD) para la estimación continua de PAS, PAD y PAM a partir de derivaciones de electrocardiografía
**Documento:** `reports/data_quality_report.md`, versión 1.1.0
**Fecha de edición:** 20 de septiembre de 2026
**Estado del documento:** criterios instrumentados y **primera caracterización sobre PulseDB v2.0**: catálogo completo (5 361 sujetos, 5 245 454 segmentos) y muestra de formas de onda (41 sujetos, 2 042 ventanas). Las puertas no se firman (véase la sección 10)

| Área | Responsable | Secciones bajo su dirección |
|---|---|---|
| Validación Clínica | Juan Manuel Buitrago | 3 (admisibilidad hemodinámica bajo ANSI/AAMI/ISO 81060-2) |
| Ingeniería TI | Luis Carlos Rocha | 4 (estadísticas univariadas, bivariadas y saturación), 7 (visualizaciones), 8 (verificación funcional) |
| Ética y Pacientes | German Alberto Hidalgo | 5 (balance de retención y rechazo derivado de los SQI), 6 (verificación de equidad demográfica) |

---

## 1. Alcance y estado

### 1.1 Objeto

El DQR es el entregable técnico formal que documenta el diagnóstico numérico, la admisibilidad fisiológica y el cumplimiento metrológico de los datos crudos y procesados antes de su uso en las tareas de inferencia predictiva de la Fase 3. Cubre las series de ECG de la derivación II, las etiquetas de presión arterial del comparador clínico, los índices de calidad de señal (RF4) y la composición demográfica de la cohorte (R2, S4).

### 1.2 Estado de los datos

El corpus disponible es **PulseDB v2.0**, una base pública derivada de MIMIC-III (unidades de cuidados intensivos) y VitalDB (cirugía), en la que cada segmento de 10 s a 125 Hz trae ECG, fotopletismografía y la presión arterial invasiva (PAS, PAD) medida por catéter arterial como etiqueta. Se instaló en `data/raw/datos_drive/PulseDB_v2_0/` (603 GB). El equipo trabajó con dos niveles de lectura:

1. **Catálogo completo (nivel de etiquetas).** Se leyó el archivo `Info_Files/PulseDB_Info.mat` para los 5 361 sujetos y 5 245 454 segmentos (sección 3, cuotas ISO, composición demográfica, censura). No requiere abrir las formas de onda.
2. **Muestra de formas de onda.** Por el tamaño del corpus y la lentitud de lectura del volumen remoto, se procesó una **muestra aleatoria y reproducible** de adultos (plan de 40 sujetos por fuente, intercalados; se completaron los primeros 41: 21 de MIMIC y 20 de VitalDB) y 2 042 ventanas (hasta 60 por sujeto, elegidas al azar), con el pipeline completo de la Fase 2: filtrado causal a 125 Hz, compuerta SQI, 65 características y latencia (secciones 4, 5 y 8.4). Una línea del archivo de salida quedó truncada por una interrupción y se descartó (2 042 ventanas válidas).

Alcance y límites que condicionan la lectura de todo el informe:

- La muestra de ondas (41 sujetos, 0.8 % de los sujetos adultos) sirve para **diagnosticar** la compuerta, la sincronización y las características, no para estimar tasas poblacionales con precisión. Sus cifras llevan esa cautela y no pueden usarse para congelar umbrales: la calibración final debe hacerse solo con sujetos de la partición `train` (puerta G9), y los sujetos de la muestra se eligieron al azar entre todos los adultos, por lo que algunos pueden pertenecer a `val` o `test`.
- La población es **hospitalaria** (cuidados intensivos y perioperatorio), con catéter arterial. No equivale a la población ambulatoria para la que se concibe el sistema; se trata como fuente de desarrollo inicial y no como evidencia de desempeño en el uso previsto.
- PulseDB no trae postura, medicación, comorbilidades, impedancia ni metadatos de hardware. El IMC solo existe para VitalDB. Esos campos figuran en el diccionario como "no disponible" (véase el diccionario de datos, sección 14).
- Licencias: los segmentos de MIMIC se distribuyen bajo ODbL y los de VitalDB bajo CC BY-NC-SA 4.0 (uso no comercial y compartir igual). Antes de cualquier uso comercial del sistema se requiere revisión legal (hallazgo H-14).
- Las figuras `*_pulsedb` y las tablas de este informe provienen del corpus real. Las figuras rotuladas como sintéticas (sección 8) solo verifican el funcionamiento del código.

La firma del DQR (sección 10) requiere que se cumplan los criterios de la sección 9.1; con los resultados actuales varios criterios **no** se cumplen.

### 1.3 Reproducción de las tablas y figuras

```bash
# Catálogo de metadatos y etiquetas (lee solo Info_Files; ~40 s)
python -m src.ingestion.pulsedb_catalog --info <raiz>/PulseDB_v2_0/Info_Files/PulseDB_Info.mat
# Muestra de formas de onda (reanudable; use --parte/--partes para paralelizar)
python -m src.ingestion.pulsedb_sample --raiz-pulsedb <raiz>/PulseDB_v2_0 \
    --n-por-fuente 40 --k-ventanas 60
# Particiones anti-fuga y certificado de intersección vacía
python -m src.partitioning.partition_pulsedb
# Tablas, estadísticas y figuras reales de este informe
python -m src.reports.pulsedb_dqr_analysis
# Verificación funcional (figuras rotuladas como sintéticas)
python -m src.reports.generate_visualizations --synthetic-demo
```

---

## 2. Fuentes, supuestos y trazabilidad

| Elemento | Descripción | Evidencia requerida |
|---|---|---|
| Fuentes de datos | PulseDB v2.0 (MIMIC-III y VitalDB): ventanas de 10 s a 125 Hz con ECG y presión arterial invasiva por catéter como referencia | Catálogo `data/processed/pulsedb_catalogo/` y módulos 1 y 4 del esquema de metadatos |
| S1 - Calidad certificada de la referencia | Cada sesión declara la norma de validación del comparador; las sesiones con `none_documented` no se certifican. En PulseDB la referencia es presión invasiva de monitores hospitalarios sin certificado por sesión (véase 3.3) | Porcentaje de sesiones certificadas |
| S2 - Volumen suficiente | Número de sujetos, horas y cobertura del espacio hemodinámico | Secciones 3.4 y 6 |
| S3 - Sincronización | Desfase y deriva entre ECG y referencia | Metadatos del módulo 4 y sección 3.3 |
| S4 - Representatividad | Composición frente a la población objetivo | Sección 6 |
| Versión de datos | `dataset_version` y huellas SHA-256 de los archivos de entrada | Registro de versiones (diccionario de datos, sección 11) |
| Versión de esquema | `schema_version = 1.1.0` | Validación de metadatos: 100 % de registros conformes |

Cada tabla de este informe se genera con la versión de código, la configuración y las huellas de datos declaradas en el encabezado del artefacto que la produce, de modo que cualquier cifra sea reproducible.

---

## 3. Admisibilidad hemodinámica bajo ANSI/AAMI/ISO 81060-2 (dirección: Juan Manuel Buitrago)

### 3.1 Protocolo de censura clínica de etiquetas (RF3, S1, R3)

Se excluyen del corpus de entrenamiento las lecturas de referencia que cumplan alguna de las condiciones siguientes, aplicadas en el orden de prioridad indicado (`filters.censor_reference_labels`). Los límites son inclusivos para los valores admisibles.

| Prioridad | Condición de exclusión | Código | Interpretación clínica |
|---|---|---|---|
| 1 | Valor no finito | 1 | Lectura ausente o corrupta |
| 2 | PAS < 70 o PAS > 240 mmHg | 2 | Despresurización incompleta o transitorio mecánico |
| 3 | PAD < 40 o PAD > 140 mmHg | 3 | Ídem |
| 4 | PAS menor o igual a PAD | 4 | Inversión fisiológicamente imposible |
| 5 | Presión de pulso (PAS - PAD) < 20 mmHg | 5 | Artefacto de amortiguamiento o lectura errónea |
| 6 | Presión de pulso mayor al límite superior (no fijado en esta versión) | 6 | Reservado; desactivado por defecto |

La supervisión clínica advierte que la censura no debe suprimir fluctuaciones patológicas reales (por ejemplo, incrementos de presión inducidos por estrés agudo). Por eso se reporta la exclusión por motivo y por estrato de PAS (riesgo V-17) y las lecturas excluidas más próximas a los límites se someten a revisión clínica por muestreo.

### 3.2 Balance de la censura de etiquetas

Resultado sobre las 5 245 454 etiquetas del catálogo completo (PulseDB ya filtra parte de los segmentos, de modo que la censura del proyecto es adicional):

| Motivo de exclusión | Lecturas excluidas (n) | Porcentaje del total | Observaciones |
|---|---|---|---|
| Valor no finito | 0 | 0.00 % | Sin etiquetas ausentes en el catálogo |
| PAS < 70 mmHg | 12 388 | 0.24 % | |
| PAS > 240 mmHg | 72 | < 0.01 % | |
| PAD < 40 mmHg | 125 724 | 2.40 % | Principal causa de exclusión |
| PAD > 140 mmHg | 1 960 | 0.04 % | |
| Presión de pulso < 20 mmHg | 36 381 | 0.69 % | |
| **Total excluido (lecturas únicas)** | **162 337** | **3.09 %** | MIMIC 3.56 %, VitalDB 1.88 % |

Las filas por condición pueden solaparse (una lectura puede incumplir más de una); el total cuenta cada lectura una vez. Los valores mínimos y máximos observados (PAS de 13 a 287 mmHg y PAD de 1.2 a 278 mmHg) confirman que el corpus incluye segmentos no fisiológicos que la censura elimina. La exclusión es 1.9 veces mayor en MIMIC que en VitalDB, de modo que la censura **no** es neutra entre fuentes (véase el riesgo V-17). La revisión clínica por muestreo de las lecturas excluidas próximas a los límites queda pendiente.

En la muestra de ondas, 64 de 2 042 ventanas (3.1 %) tuvieron etiqueta censurada (motivo PAD < 40: 42; presión de pulso < 20: 16; PAS fuera de rango: 5; valor no finito: 1), cifra coherente con la del catálogo.

### 3.3 Estabilidad de la referencia y sincronización (R3, S3)

| Indicador | Definición | Criterio | Valor observado |
|---|---|---|---|
| Lecturas inestables en reposo | Variación de PAS > 15 mmHg en 120 s (`flag_unstable_reference`) | Reportar porcentaje; excluir del promedio de referencia | No evaluable: los segmentos de PulseDB no tienen marcas de reposo |
| Desfase absoluto ECG-referencia | Campo `ABP_Lag` de PulseDB (muestras a 125 Hz, 8 ms por muestra) | < 50 ms en el 100 % de las ventanas | **No cumple**: 99.7 % de las 2 041 ventanas con `ABP_Lag` tienen desfase absoluto > 50 ms |
| Incertidumbre temporal por ciclo | `sync_uncertainty_ms` | <= 10 ms en al menos el 95 % de los ciclos | No evaluable: no hay señal de reloj compartida |
| Deriva de reloj | `clock_skew_tolerance_ppm` | < 10 ppm | No evaluable con los datos públicos |
| Incertidumbre del comparador | `reference_measurement_uncertainty_mmhg` y `s_ref` por Bland-Altman | Reportar; define el piso de error irreducible (V-06) | No evaluable: no hay lecturas repetidas del comparador |
| Sesiones con comparador certificado | `reference_validation_standard` distinto de `none_documented` | 100 % (puerta G5) | 0 %: sin certificado por sesión, la evidencia es el estándar clínico del monitor |

El desfase `ABP_Lag` (figura 2) tiene medianas de +280 ms en MIMIC y de -176 ms en VitalDB, con rangos de -792 a +376 ms y de -776 a +528 ms; en el 27 % de las transiciones entre ventanas consecutivas de un mismo sujeto el signo del desfase cambia. Este campo lo calcula PulseDB al alinear señales de distinto canal, y su definición exacta debe confirmarse en la documentación de la base. Con independencia de su origen, dos consecuencias son claras: (i) el supuesto S3 (cero jitter y desfase < 50 ms entre ECG y presión de referencia) **no está garantizado** por la fuente; (ii) para un estimador cuya relación con la presión depende del tiempo de tránsito del pulso, una incertidumbre de alineación de cientos de milisegundos es del orden de la señal que se busca. Además, la correlación entre fotopletismografía y presión (`PPG_ABP_Corr`, media 0.947 en MIMIC y 0.943 en VitalDB, mínimo 0.90) muestra que PulseDB solo conserva segmentos con buena concordancia interna, lo que puede hacer optimista cualquier evaluación (hallazgo H-9).

![Desfase ABP_Lag reportado por PulseDB, por fuente (muestra de formas de onda; la banda gris marca el criterio de ±50 ms)](figures/pulsedb/retardo_abp_pulsedb.png){width=80%}

### 3.4 Cuotas de distribución poblacional de las etiquetas

La norma ANSI/AAMI/ISO 81060-2 exige que la distribución de las presiones de referencia no se concentre en el rango normotenso. El plan fija un mínimo del 5 % de lecturas en cada uno de cuatro rangos críticos. Los valores numéricos están parametrizados en `generate_visualizations.ISO_QUOTAS` y **deben contrastarse con el texto vigente de la norma licenciada antes de la firma del DQR**.

Resultado en el catálogo completo, con las lecturas admisibles tras la censura (entre paréntesis, la cohorte sin censurar):

| Rango crítico | Fracción mínima | Fracción observada (admisibles) | Sin censurar | Veredicto |
|---|---|---|---|---|
| PAS <= 100 mmHg | 5 % | 15.32 % | 16.62 % | Cumple |
| PAS >= 160 mmHg | 5 % | 5.34 % | 5.21 % | Cumple (margen estrecho) |
| PAD <= 60 mmHg | 5 % | 46.94 % | 48.03 % | Cumple |
| PAD >= 100 mmHg | 5 % | **0.65 %** | 0.78 % | **No cumple** |

Por fuente (sin censurar): MIMIC cumple los tres rangos de PAS y PAD bajos y no cumple PAD >= 100 (0.94 %); VitalDB no cumple PAS >= 160 (1.86 %) ni PAD >= 100 (0.36 %). Es decir, **solo la unión de las dos fuentes alcanza la cuota de PAS elevada** y, en ningún caso, la de PAD elevada. La distribución de PAS/PAD tiene medias de 123.7/61.5 mmHg (MIMIC) y 115.5/62.8 mmHg (VitalDB); la correlación de Spearman entre PAS y PAD es 0.579. El 1 % de los sujetos con más segmentos aporta el 10.7 % de las etiquetas (concentración moderada; véase V-05).

![Distribución de PAS y PAD del corpus PulseDB con las cuotas de ISO 81060-2](figures/pulsedb/histograma_pas_pad_pulsedb.png){width=95%}

Las cuotas se evalúan sobre las lecturas admisibles de cada partición (`train`, `val`, `test`) y de la cohorte completa; la partición de prueba debe cumplirlas por sí misma para que el desempeño pueda evaluarse en los extremos. Con PAD >= 100 mmHg en 0.65 % de las lecturas, el desempeño **no podrá afirmarse** en la cola diastólica alta; el equipo propone (a ratificar por Buitrago) declararla como limitación de alcance de uso o complementar con una fuente con hipertensión diastólica, y reportar el error por estrato de PAS y PAD en la Fase 3.

### 3.5 Alcance de la norma (advertencia metodológica)

ANSI/AAMI/ISO 81060-2 establece los requisitos de validación clínica de esfigmomanómetros no invasivos **intermitentes** (con manguito). El sistema AASIM es un estimador continuo sin manguito. La norma resulta aplicable como referencia de calidad de las etiquetas y de la distribución poblacional, pero los criterios de aceptación finales de exactitud del sistema requieren evaluar, además, las normas para dispositivos continuos (ANSI/AAMI/ISO 81060-3) y la norma IEEE 1708 para dispositivos portátiles sin manguito. La decisión se documenta como puerta G10 del informe de riesgos.

### 3.6 Criterio de aceptación clínica

El área clínica certifica las etiquetas maestras cuando se cumplan simultáneamente: (a) el 100 % de las sesiones incluidas tiene comparador con norma de validación documentada; (b) las cuatro cuotas de la sección 3.4 se cumplen en la cohorte y en la partición de prueba; (c) el desfase y la incertidumbre temporal cumplen los criterios de la sección 3.3; (d) la revisión clínica por muestreo de las lecturas excluidas no encuentra patología real suprimida de forma sistemática.

**Estado:** **no certificable con los datos actuales**. Los criterios (b) y (c) no se cumplen (PAD >= 100 mmHg en 0.65 %; desfase de alineación mayor de 50 ms en casi todas las ventanas) y los criterios (a) y (d) no son evaluables con datos públicos. La certificación clínica se aplaza y queda sujeta a la decisión de la puerta G1; no se estampa firma en la sección 10.

---

## 4. Estadísticas univariadas, bivariadas y tasas de saturación (dirección: Luis Carlos Rocha)

### 4.1 Señal de ECG cruda y procesada

Resultados sobre la muestra de formas de onda (2 042 ventanas de 10 s a 125 Hz, derivación de ECG de PulseDB). Las tasas de saturación e impedancia no son observables con los datos públicos.

| Variable | Unidad | Criterio de aceptabilidad | Valor observado |
|---|---|---|---|
| ECG crudo (125 Hz, fija) | mV | Sin criterio (escala definida por PulseDB) | Desviación estándar mediana 0.146 mV (MIMIC) y 0.142 mV (VitalDB); amplitud pico a pico mediana 1.0 mV en ambas fuentes, lo que indica ECG normalizado por PulseDB |
| Tasa de saturación (`saturation_fraction`) | fracción | Propuesta: <= 1 % por sesión (a ratificar) | No evaluable: la señal pública está normalizada y no conserva los rieles del ADC |
| Tramos planos (`flatline_fraction`) | fracción | Reportar | 0 % de las ventanas con tramos planos |
| Discontinuidades | - | Más de 200 ms: ventana descartada | Una ventana con valores no finitos (0.05 %), descartada |
| Interferencia de red | Hz | Reportar | Detectada en 41.7 % (MIMIC) y 33.7 % (VitalDB) de las ventanas. Frecuencia: MIMIC predominantemente 60 Hz (330 de 439); VitalDB predominantemente 50 Hz (320 de 333) |
| Impedancia electrodo-piel | kOhm | <= 50 kOhm en el 100 % | No disponible en PulseDB |
| Frecuencia cardíaca (ventanas aceptadas) | lpm | Ritmo sinusal verificado | 82.3 +- 16.8 lpm; P5 55.7; mediana 81.5; P95 108.7; rango 47.8-150.0 |

**Hallazgo (H-13).** La frecuencia de red que estima el detector es 50 Hz en la mayoría de las ventanas de VitalDB y 60 Hz en las de MIMIC. Como VitalDB se recopiló en un hospital de Corea del Sur (red de 60 Hz), la frecuencia detectada no coincide con la esperada; el equipo no pudo determinar si se debe a la naturaleza de la señal de origen, al remuestreo que aplica PulseDB o a una confusión del detector. El notch adaptativo actúa sobre la frecuencia detectada; la verificación del espectro (figura 3) no muestra picos residuales, pero conviene confirmar el origen antes de fijar el diseño del notch en el dispositivo.

### 4.2 Etiquetas de presión arterial (catálogo completo)

| Variable | Unidad | Fuente | Media | DE | P1 | Mediana | P99 | Mín. - máx. |
|---|---|---|---|---|---|---|---|---|
| PAS | mmHg | MIMIC | 123.7 | 22.7 | 79.5 | 121.9 | 181.9 | 13.0 - 267.3 |
| PAS | mmHg | VitalDB | 115.5 | 19.1 | 77.4 | 114.0 | 166.4 | 22.5 - 286.6 |
| PAD | mmHg | MIMIC | 61.5 | 13.3 | 36.3 | 60.0 | 99.4 | 1.2 - 230.2 |
| PAD | mmHg | VitalDB | 62.8 | 12.1 | 38.0 | 62.0 | 94.0 | 2.4 - 277.9 |

La presión arterial media (PAM) no figura en los archivos de PulseDB; se calculará como `PAD + (PAS - PAD)/3` o a partir de la curva completa si se dispone de ella. La presión de pulso queda por encima de 20 mmHg tras la censura por construcción. La tabla completa de cuantiles se genera con `pulsedb_dqr_analysis`.

### 4.3 Análisis bivariado

Ventanas aceptadas por la compuerta (n = 1 109; la correlación es de Spearman y se calcula con ventanas, no con sujetos independientes, por lo que la incertidumbre real es mayor que la sugerida por el tamaño de muestra):

| Par de variables | Método | Propósito | Valor observado |
|---|---|---|---|
| PAS - PAD (catálogo completo) | Spearman | Coherencia de las etiquetas | rho = 0.579 |
| Cada `feat_*` - PAS, PAD | Spearman | Acoplamiento fisiológico antes del entrenamiento | Máximo |rho| = 0.37 (PAS con homogeneidad GLCM del QRS y con su contraste, de signo opuesto). Para PAD: amplitud de R (+0.33), duración del QRS (-0.28) |
| Frecuencia cardíaca - PAS, PAD | Spearman | Detección de confusión por frecuencia cardíaca | PAS: -0.13; PAD: +0.13 |
| Diferencia frente a media de lecturas del comparador | Bland-Altman | Heterocedasticidad del comparador (R3) | No evaluable: PulseDB no trae lecturas repetidas del comparador |
| Calidad de señal - error de referencia | Spearman | Dependencia calidad-etiqueta | Pendiente (requiere el error de un modelo; Fase 3). En su lugar se reporta el rechazo por estrato de PAS en la sección 5.4 |

**Lectura.** Ninguna característica supera |rho| = 0.4 con la presión, y las asociaciones más altas corresponden a descriptores de textura del QRS y a la amplitud de la onda R, que dependen de la ganancia del registro y de la posición del electrodo y no de la hemodinámica; deben vigilarse por posible confusión (H-11). La correlación de VLF es indefinida (valor constante) en ventanas de 10 s, como se anticipó en H-3. No se dibuja el mapa de calor completo de 65 características en este informe por su tamaño; se conserva en `figures/pulsedb/correlacion_spearman_pulsedb.png`.

### 4.4 Pérdida global neta de señal

**Definición.** La pérdida global neta se calcula como

`pérdida = 1 - H_retenidas / H_adquiridas`,

donde `H_adquiridas` son las horas totales de señal adquirida y `H_retenidas` son las horas de ventanas que simultáneamente (i) superan la compuerta RF4 (`quality_flag = 0`), (ii) no contienen discontinuidades no reparadas y (iii) cuentan con una etiqueta de referencia admisible y sincronizada. El criterio de aceptación (puerta G1) exige **pérdida < 15 %**.

Resultado en la muestra de ondas (unidad: ventanas de 10 s, 2 042 en total; todas de igual duración, de modo que fracción de ventanas equivale a fracción de horas):

| Componente | Ventanas | Porcentaje de las adquiridas |
|---|---|---|
| Ventanas evaluadas | 2 042 | 100 % |
| Perdidas por discontinuidades o saturación | 1 | 0.05 % |
| Perdidas por rechazo de calidad (`quality_flag = 1`), sin las anteriores | 932 | 45.6 % |
| Perdidas por etiqueta no admisible entre las retenidas | 20 | 1.0 % |
| **Pérdida global neta** | **953** | **46.7 %** (criterio: < 15 %) |

**La puerta G1 no se cumple**, y la causa casi exclusiva es el criterio pSQI (sección 5.2). No se sincronizó la etiqueta con la señal (desfase de la sección 3.3), por lo que esta pérdida es un mínimo. Como el resultado depende de la muestra (41 sujetos con rechazo muy variable entre sujetos: mediana 43 %, cuartil superior 90 %), la estimación tiene una incertidumbre amplia y se debe repetir con más sujetos; con todo, la magnitud excede tres veces el criterio.

---

## 5. Compuerta de calidad de señal y balance de retención y rechazo (dirección: German Alberto Hidalgo)

### 5.1 Definición de la compuerta (RF4, R4)

Se computan tres índices sobre cada ventana de ECG filtrado (0.5-45 Hz) y se aplica la compuerta lógica combinada. Un cuarto índice, la asimetría (sSQI), se registra como información auxiliar.

| Índice | Definición | Umbral | Falla típica que detecta |
|---|---|---|---|
| bSQI | Puntuación F1 de latidos coincidentes entre Pan-Tompkins y el detector de longitud de curva, tolerancia 50 ms | >= 0.85 | Artefactos de movimiento y pérdida de contacto |
| kSQI | Curtosis de Pearson en bloques de 5 s, mediana entre bloques | >= 5.0 | Ruido incoherente (curtosis cercana a 3) y saturación (subgaussiana) |
| pSQI | Potencia en 5-15 Hz sobre potencia en 1-40 Hz | >= 0.50 | Deriva de línea base y ruido electromiográfico |
| sSQI | Tercer momento estandarizado | Informativo | Desprendimiento parcial de electrodos |

`quality_flag = 0` si y solo si se cumplen los tres criterios; en cualquier otro caso `quality_flag = 1`, no se calcula ninguna estimación de presión arterial y se notifica la causa del descarte al usuario indicando el reposicionamiento de electrodos.

### 5.2 Balance global de retención y rechazo

Muestra de ondas (2 042 ventanas de 10 s; umbrales del plan sin modificar):

| Concepto | Ventanas | Porcentaje |
|---|---|---|
| Ventanas evaluadas | 2 042 | 100 % |
| Retenidas (`quality_flag = 0`) | 1 109 | 54.3 % |
| Rechazadas (`quality_flag = 1`) | 933 | 45.7 % |
| Rechazadas por bSQI | 77 | 3.8 % |
| Rechazadas por kSQI | 131 | 6.4 % |
| Rechazadas por pSQI | 927 | 45.4 % |
| Rechazadas solo por pSQI | 750 | 36.7 % |
| Rechazadas por más de un criterio | 177 | 8.7 % |
| Rechazo por fuente | MIMIC 41.7 %; VitalDB 49.9 % | |

Un mismo evento de rechazo puede contar en varios criterios; por ello las filas por criterio no suman el total de rechazadas. El balance se acumula con `quality_assessment.RejectionBalance`.

**Hallazgo (H-8).** El criterio pSQI explica el 99 % de los rechazos (927 de 933) y, en 750 ventanas, es el único que falla. Las medianas de los índices son bSQI = 1.00 y kSQI de 13.3 (MIMIC) y 13.7 (VitalDB), muy por encima de sus umbrales (0.85 y 5.0), mientras que la mediana de pSQI es 0.52 (MIMIC) y 0.50 (VitalDB), es decir, **el umbral de 0.50 cae sobre la mediana de la población**. El umbral fijado por el plan no discrimina calidad en este corpus: descarta casi la mitad de las ventanas aunque los latidos se detecten correctamente. En efecto, la concordancia (F1) entre nuestro detector de picos R y las anotaciones de PulseDB tiene mediana 1.00; solo el 0.45 % de las ventanas aceptadas y el 19.5 % de las rechazadas presentan F1 < 0.9, y entre las 750 ventanas rechazadas únicamente por pSQI solo el 10.5 % tiene F1 < 0.9. La compuerta sí concentra las ventanas con detección deficiente entre las rechazadas (utilidad de bSQI y kSQI), pero el pSQI con umbral 0.50 elimina además un gran volumen de señal utilizable.

![Espectros de potencia (PSD) de ventanas aceptadas y rechazadas de PulseDB](figures/pulsedb/psd_aceptadas_vs_rechazadas_pulsedb.png){width=85%}

La figura 3 (PSD) se construyó con 108 ventanas aceptadas y 114 rechazadas; las curvas son similares en forma, lo que concuerda con la pérdida de discriminación del pSQI. No se observan picos residuales en la frecuencia de red y la atenuación bajo 0.5 Hz y sobre 45 Hz es la esperada.

### 5.3 Rechazo por sujeto y auditoría individual

Los sujetos cuya tasa de descarte supere el **30 %** se marcan para auditoría clínica individualizada (`rejection_by_subject`; `qc_review_required = true` en el metadato de la sesión). Los sujetos se identifican únicamente por `subject_id`.

| Indicador | Criterio | Valor observado |
|---|---|---|
| Sujetos con tasa de rechazo > 30 % | Listar y auditar | 22 de 41 (53.7 %) |
| Sujetos con rechazo >= 90 % | Auditar | 11 de 41 |
| Sujetos sin ningún rechazo | Reportar | 6 de 41 |
| Cuantiles de la tasa de rechazo por sujeto | Reportar | P25 = 5 %, mediana = 43 %, P75 = 90 %, P90 = 100 % |
| Evolución longitudinal del rechazo | Detectar deterioro progresivo del contacto | No evaluable: las ventanas de la muestra se eligen al azar y PulseDB no publica su orden temporal continuo |

La distribución es **bimodal a nivel de sujeto**: la mayoría de los sujetos o casi no se rechaza o casi se rechaza por completo. Esa estructura sugiere que el rechazo depende de características de la señal propias de cada sujeto (morfología, amplitud relativa del QRS, ritmo) más que de artefactos ocasionales, lo que refuerza el hallazgo H-8. Por regla, 22 sujetos entrarían a auditoría individual; se propone auditar con Buitrago una submuestra antes de aplicar el descarte definitivo.

### 5.4 Sesgo de selección por rechazo (riesgo V-09)

El rechazo por SQI no es aleatorio. Como el rechazo condiciona la muestra que llega al entrenamiento, se reporta por subgrupo y se aplica el criterio de cociente máximo de 1.5 entre subgrupos (puerta G8). En la muestra de ondas (las celdas con menos de 5 sujetos se agrupan; el estrato de edad 18-39 tenía 4 sujetos y se unió con 40-64):

| Dimensión | Subgrupo | Sujetos | Ventanas | Rechazo (%) | pSQI mediana |
|---|---|---|---|---|---|
| Fuente | MIMIC | 21 | 1 053 | 41.7 | 0.524 |
| Fuente | VitalDB | 20 | 989 | 49.9 | 0.501 |
| Sexo | Femenino | 19 | 883 | 39.9 | 0.525 |
| Sexo | Masculino | 22 | 1 159 | 50.1 | 0.500 |
| Edad | 18-64 años | 29 | 1 433 | 35.0 | 0.534 |
| Edad | 65 años o más | 12 | 609 | 70.8 | 0.415 |
| Estrato de PAS | <= 100 mmHg | 29 | 426 | 41.8 | 0.521 |
| Estrato de PAS | 101-139 mmHg | 39 | 1 309 | 45.0 | 0.514 |
| Estrato de PAS | 140-159 mmHg | 24 | 199 | 46.7 | 0.509 |
| Estrato de PAS | >= 160 mmHg | 7 | 107 | 67.3 | 0.289 |

Los sujetos aparecen en varios estratos de PAS porque el estrato se asigna por ventana. Cocientes máximo/mínimo: fuente 1.20; sexo 1.26; **edad 2.02**; **estrato de PAS 1.61**. **La puerta G8 (cociente <= 1.5) no se cumple** en edad ni en PAS: los sujetos de 65 años o más pierden el 71 % de sus ventanas y las ventanas con PAS >= 160 mmHg el 67 %. Esto es el escenario de riesgo V-09: la compuerta retira desproporcionadamente los adultos mayores y las presiones altas, con lo cual la muestra retenida sería más joven y más normotensa que la población de estudio, y el modelo aprendería a estimar bien justamente donde es más fácil (regresión hacia la media, V-01).

![Rechazo de señal por subgrupo (muestra de PulseDB); la línea discontinua marca el umbral de auditoría del 30 %](figures/pulsedb/rechazo_por_subgrupo_pulsedb.png){width=85%}

### 5.5 Calibración de umbrales

Los umbrales de la sección 5.1 son los fijados por el plan. La verificación con señal sintética ya advertía un margen estrecho del pSQI (H-1); los datos reales lo confirman. Como análisis **exploratorio** (solo sobre la muestra de ondas, no para congelar umbrales), el efecto de bajar el umbral del pSQI con bSQI >= 0.85 y kSQI >= 5.0 fijos es el siguiente:

| Umbral de pSQI | Rechazo global (%) | Rechazo 18-64 años (%) | Rechazo >= 65 años (%) | Cociente de edad |
|---|---|---|---|---|
| 0.50 (plan) | 45.7 | 35.0 | 70.8 | 2.02 |
| 0.45 | 33.3 | 23.4 | 56.5 | 2.41 |
| 0.40 | 22.8 | 12.8 | 46.5 | 3.64 |
| 0.35 | 16.3 | 7.2 | 37.6 | 5.23 |
| 0.30 | 13.2 | 4.7 | 33.2 | 7.09 |

Ninguna calibración sencilla del pSQI cumple a la vez la pérdida < 15 % (G1) y el cociente <= 1.5 entre grupos de edad (G8): al bajar el umbral, el rechazo disminuye más en los menores de 65 años que en los mayores y el cociente **aumenta**. Esto indica que el pSQI, tal como se definió (potencia en 5-15 Hz sobre potencia en 1-40 Hz), mide una propiedad de la morfología del registro correlacionada con la edad y no solo su calidad. El equipo propone (Rocha e Hidalgo): (i) sustituir o complementar el pSQI por un índice normalizado por sujeto o por un criterio basado en la razón señal-ruido del complejo QRS; (ii) evaluar el índice con anotaciones de calidad humanas; (iii) repetir el análisis con los sujetos de `train` y `val` (nunca de `test`) y congelar umbrales y huella en el registro de versiones antes de consultar la partición de prueba (puerta G9). Mientras tanto, RF4 se mantiene operativa con los umbrales del plan en la implementación de referencia, pero su uso con datos de PulseDB para entrenar produciría el sesgo descrito en 5.4.

---

## 6. Verificación de equidad demográfica (dirección: German Alberto Hidalgo)

### 6.1 Composición de la cohorte

Se reporta, para la cohorte de adultos del catálogo (5 332 de 5 361 sujetos; se excluyen 29 menores de 18 años, fuera del alcance de uso), el número de sujetos por estrato. **Toda celda con menos de 5 sujetos se suprime o se agrupa** (RNF1); el estrato de edad 18-39 se agrupa en la muestra de ondas por tener 4 sujetos.

| Dimensión | Estratos | Sujetos (n) | Porcentaje | Referencia poblacional declarada | Diferencia estandarizada |
|---|---|---|---|---|---|
| Edad | 18-39 / 40-64 / >= 65 años | 491 / 2 522 / 2 319 | 9.2 % / 47.3 % / 43.5 % | No declarada | No evaluable |
| Sexo biológico | Femenino / masculino | 2 333 / 2 999 | 43.8 % / 56.2 % | No declarada | No evaluable |
| Índice de masa corporal | Disponible solo en VitalDB (2 938 sujetos): media 23.1, DE 3.5, P25 20.7, P75 25.1, rango 11.5-43.2 | 2 938 (54.8 % del catálogo) | MIMIC: 0 % con IMC | No declarada | No evaluable |
| Hipertensión basal (AHA/ACC) | No disponible (sin diagnóstico ni medición basal). Sustituto: PAS mediana del sujeto >= 130 / >= 140 / >= 160 mmHg | - | 22.3 % / 10.5 % / 1.9 % | No declarada | No evaluable |
| Comorbilidades | No disponibles | - | - | - | - |
| Centro | SITE-001 (MIMIC) / SITE-002 (VitalDB) | 2 421 / 2 911 | 45.4 % / 54.6 % | - | - |

Las composiciones por fuente y por edad-sexo son:

| Fuente / edad | Femenino | Masculino |
|---|---|---|
| MIMIC / 18-39 | 78 | 112 |
| MIMIC / 40-64 | 419 | 620 |
| MIMIC / >= 65 | 520 | 672 |
| VitalDB / 18-39 | 159 | 142 |
| VitalDB / 40-64 | 720 | 763 |
| VitalDB / >= 65 | 437 | 690 |

La cohorte procede de dos hospitales (cuidados intensivos de Estados Unidos y cirugía de Corea del Sur) y no incluye información de raza, etnia ni comorbilidades, de modo que **no se puede auditar la representatividad frente a subgrupos protegidos más allá de edad, sexo y fuente** (riesgo V-14, supuesto S4). Se documenta como limitación: cualquier afirmación de equidad se restringe a esas tres dimensiones.

### 6.2 Cuotas mínimas y evaluabilidad (valores propuestos)

| Criterio | Umbral propuesto | Valor observado | Veredicto |
|---|---|---|---|
| Sujetos de 65 años o más | >= 20 % de la cohorte de entrenamiento | 43.5 % (train: 43.5 %) | Cumple |
| Hipertensión basal en estadio 1 o 2 | >= 25 % de la cohorte de entrenamiento | No evaluable; con PAS mediana >= 130 mmHg como sustituto, 22.3 %; con >= 140 mmHg, 10.5 % | No cumple con el sustituto (a verificar; la PAS de pacientes sedados o anestesiados no representa la presión basal) |
| Sujetos por subgrupo evaluable | >= 30 | Catálogo: mínimo 78 por fuente, edad y sexo. Muestra de ondas: 12 sujetos de 65 años o más | Cumple en el catálogo; no en la muestra de ondas |
| Cociente de tasas de rechazo por SQI entre subgrupos | <= 1.5 | Edad 2.02; estrato de PAS 1.61; sexo 1.26; fuente 1.20 | **No cumple** (sección 5.4) |
| Cociente de tasas de exclusión de etiquetas entre subgrupos | Reportar; revisión clínica si > 1.5 | Fuente 1.90 (MIMIC 3.56 %, VitalDB 1.88 %); edad y sexo pendientes | Requiere revisión clínica |

Los umbrales numéricos son propuestas del equipo, dado que el plan de la Fase 1 exige cuotas mínimas sin fijar el valor; deben ratificarse antes de la Fase 3.

### 6.3 Verificación cruzada con la partición

La partición **patient-wise 70/15/15** del catálogo de adultos (semilla 20260920, estratificada por fuente, grupo de edad, sexo y estrato de PAS mediana; 60 estratos) se generó con `src/partitioning/partition_pulsedb.py`. Los estratos con menos de 5 sujetos existen (mínimo 1) pero no se reportan individualmente.

| Partición | Sujetos | MIMIC | VitalDB | Edad media (años) | Mujeres (%) | PAS mediana media (mmHg) | >= 65 años (%) |
|---|---|---|---|---|---|---|---|
| `train` | 3 732 | 1 695 | 2 037 | 61.2 | 43.8 | 117.4 | 43.5 |
| `val` | 800 | 363 | 437 | 61.0 | 43.8 | 117.6 | 43.4 |
| `test` | 800 | 363 | 437 | 61.1 | 43.8 | 117.4 | 43.5 |

La composición es prácticamente idéntica entre particiones. El certificado criptográfico (`assert_disjoint_subjects`) confirma intersección vacía entre `train`, `val` y `test` tanto por identificador como por huella hash (0 sujetos en las tres intersecciones); la huella SHA-256 del manifiesto es `cbaf2aaf9202c73871e13bfc0785d26333d8be788b79456ed988badf7d390b4e`.

Con solo **dos centros**, la partición site-wise 70/15/15 no es realizable (exige tres o más). Se generó en su lugar la validación *leave-one-site-out*: con SITE-001 (MIMIC) como prueba externa, 2 397 sujetos de VitalDB para entrenamiento, 514 para validación y 2 421 de MIMIC en prueba; con SITE-002 (VitalDB) como prueba externa, 1 994, 427 y 2 911. Esta configuración mide generalización entre hospitales, pero cada centro es también un tipo distinto de paciente (cuidados intensivos frente a cirugía).

Cuotas ISO 81060-2 por partición (lecturas admisibles):

| Partición | Lecturas | PAS <= 100 | PAS >= 160 | PAD <= 60 | PAD >= 100 |
|---|---|---|---|---|---|
| `train` | 3 524 872 | 15.2 % | 5.5 % | 47.2 % | 0.66 % |
| `val` | 770 292 | 14.8 % | 5.2 % | 43.7 % | 0.41 % |
| `test` | 772 397 | 15.5 % | **4.7 %** | 48.5 % | **0.86 %** |

La partición de prueba no cumple la cuota de PAS >= 160 mmHg (4.7 %) ni la de PAD >= 100 mmHg; la primera queda a 0.3 puntos del umbral y la estratificación por PAS mediana no la garantiza porque el estrato es del sujeto, no de la lectura.

### 6.4 Criterio de aceptación de equidad

El área de Ética y Pacientes certifica la verificación de equidad cuando: (a) la composición de la cohorte se ha comparado con la referencia poblacional declarada y las diferencias se han documentado; (b) las cuotas de la sección 6.2 se cumplen o las desviaciones se han declarado como limitación de alcance de uso; (c) las tasas de rechazo y de exclusión por subgrupo se han reportado; (d) ninguna celda de los informes tiene menos de 5 sujetos.

**Estado:** **no certificable con los datos actuales**. El criterio (a) no se puede cumplir (no hay referencia poblacional declarada ni variables de raza, etnia o comorbilidad); el criterio (b) no se cumple (cociente de rechazo, hipertensión); el criterio (c) está documentado; el criterio (d) se cumple en los informes (celdas con menos de 5 sujetos se agrupan). No se estampa firma en la sección 10.

---

## 7. Catálogo de visualizaciones

Las figuras se guardan en `figures/` en PNG (200 ppp) y SVG. Las figuras del corpus real están en `figures/pulsedb/` y las de verificación funcional (datos sintéticos, con marca de agua) en `figures/verificacion_sintetica/`. Todas se generan con `src/reports/generate_visualizations.py` y `src/reports/pulsedb_dqr_analysis.py`.

| Fig. | Archivo (`figures/pulsedb/`) | Propósito | Criterio de lectura | Ubicación |
|---|---|---|---|---|
| 1 | `histograma_pas_pad_pulsedb` | Verificar que la cohorte curada no converge a una masa normotensa y cumple las cuotas de la sección 3.4 | Cada cola crítica rotula fracción observada, mínimo (5 %) y veredicto | Sección 3.4 |
| 2 | `retardo_abp_pulsedb` | Sincronización ECG-referencia (S3) | Histograma del desfase por fuente frente a la tolerancia de 50 ms | Sección 3.3 |
| 3 | `psd_aceptadas_vs_rechazadas_pulsedb` | Validar el notch, la supresión bajo 0.5 Hz, el corte a 45 Hz y el perfil de las rechazadas | Mediana y rango intercuartílico de la PSD; marcas de 0.5 Hz, 45 Hz y frecuencia de red | Sección 5.2 |
| 4 | `rechazo_por_subgrupo_pulsedb` | Sesgo de selección por rechazo (V-09, G8) | Barras por subgrupo; línea de auditoría al 30 % | Sección 5.4 |
| 5 | `correlacion_spearman_pulsedb` | Acoplamiento morfología-hemodinámica antes del entrenamiento | Mapa de calor de rho de Spearman entre 64 características y PAS/PAD (VLF constante, excluida) | Archivo (no se incrusta por su tamaño) |

El diagrama de Bland-Altman del comparador (`bland_altman_referencia`) requiere lecturas repetidas o comparadas del monitor de referencia, que PulseDB no aporta; solo se genera con datos sintéticos para verificar la función. El gráfico de rechazo longitudinal (`rechazo_longitudinal`) exige el orden temporal de las ventanas, que la muestra aleatoria no conserva. Ambos quedan como entregables para la ingesta de un registro propio con comparador certificado.

### Figuras de verificación funcional (datos sintéticos)

![Bland-Altman del comparador (datos sintéticos; solo verifica el código)](figures/verificacion_sintetica/bland_altman_referencia.png){width=60%}

---

## 8. Verificación funcional del pipeline (señales sintéticas) y comportamiento en ventanas reales

**Advertencia.** Los resultados de las secciones 8.1 a 8.3 y 8.5 provienen de señales generadas por `tests/synthetic_ecg.py` con verdad-terreno conocida. Demuestran que los módulos calculan lo que declaran; no constituyen evidencia sobre la calidad, la variabilidad ni el desempeño clínico de datos reales.

### 8.1 Cadena de filtrado (RF1, R1)

| Prueba | Resultado |
|---|---|
| Estimación de la frecuencia de red con interferencia de 50 Hz y de 60.2 Hz | Detectada con error <= 0.5 Hz; sin interferencia no se aplica notch |
| Atenuación de la banda de red (49.5-50.5 Hz) en modo causal (registro sintético con 0.15 mV de interferencia) | 34.4 dB |
| Atenuación de la banda de red en modo de fase cero | 44.7 dB |
| Atenuación de la deriva (< 0.4 Hz) en modo causal (deriva sintética de 0.08 y 0.25 Hz) | 14.3 dB |
| Filtro con estado por bloques frente a filtrado del registro completo | Diferencia máxima < 1e-9 |
| Modo de fase cero en la ruta de inferencia | Rechazado con `NonCausalFilterError` |
| Notch con Q < 35 | Rechazado con `ValueError` |

### 8.2 Precisión de las características frente a la verdad-terreno

En 20 registros sintéticos de 30 s (frecuencia cardíaca de 60 a 98 lpm) tras el filtrado causal y la compuerta de calidad:

| Característica | Error absoluto medio | Error absoluto máximo |
|---|---|---|
| MeanNN | 0.04 ms | 0.07 ms |
| SDNN | 0.15 ms | 0.31 ms |
| RMSSD | 0.34 ms | 0.83 ms |

En un registro de referencia a 70 lpm el pipeline produjo 65 características finitas (22 morfológicas y de HRV, 33 de paquetes wavelet y 10 de textura GLCM), con duración QRS de 92 ms, PR de 200 ms y QT de 381 ms, valores plausibles para la morfología sintética empleada. La delineación de la onda T mediante tangente y de la onda P depende de la morfología; su exactitud debe validarse con registros anotados reales antes de emplear QT/PR como biomarcadores.

### 8.3 Compuerta de calidad (RF4, R4)

Sobre 60 ventanas sintéticas limpias y 60 degradadas de 10 s:

| Grupo | Rechazo | bSQI (mediana) | kSQI (mediana) | pSQI (mediana; mín.-máx.) | Criterios incumplidos (n de ventanas) |
|---|---|---|---|---|---|
| Limpias (ruido, deriva y red típicos) | 0 % | 1.00 | 12.6 | 0.54 (0.51-0.64) | Ninguno |
| Degradadas (ruido incoherente dominante) | 100 % | 0.77 | 3.00 | 0.27 (0.20-0.32) | kSQI: 60; pSQI: 60; bSQI: 52 |

La compuerta bloquea la inferencia cuando `quality_flag = 1` (la función de predicción no se invoca, no se emite valor numérico y se informa la causa). **Hallazgo:** el pSQI de las ventanas limpias queda cerca del umbral de 0.50, lo que sugiere una calibración cuidadosa con datos reales (sección 5.5).

### 8.4 Latencia de extremo a extremo (RNF2)

Latencia por ventana (filtrado, SQI y extracción de 65 características). Se muestra la medición sobre ventanas reales de PulseDB y las mediciones con señal sintética (20 repeticiones por condición):

| fs (Hz) | Ventana (s) | Media (s) | Percentil 95 (s) | Máximo (s) | Margen frente a 5 s |
|---|---|---|---|---|---|
| **125 (PulseDB, 2 041 ventanas reales)** | **10** | **0.013** | **0.031** | **0.094** | **53 veces** |
| 250 | 10 | 0.027 | 0.034 | 0.035 | 144 veces |
| 250 | 20 | 0.040 | 0.053 | 0.056 | 90 veces |
| 250 | 30 | 0.051 | 0.053 | 0.054 | 93 veces |
| 500 | 10 | 0.025 | 0.025 | 0.025 | 197 veces |
| 500 | 20 | 0.038 | 0.041 | 0.042 | 120 veces |
| 500 | 30 | 0.055 | 0.056 | 0.058 | 87 veces |

La primera fila (frecuencia de PulseDB) se midió con las 2 041 ventanas reales de la muestra de ondas en el equipo de trabajo (máquina virtual de 2 CPU): mediana 11.9 ms, percentil 99 43.4 ms y máximo 93.8 ms por ventana, incluido el filtrado, la compuerta SQI y las 65 características. Las demás filas se midieron con señales sintéticas en un contenedor de 2 CPU virtuales Intel Xeon a 2.8 GHz. Ninguno de estos entornos representa el hardware objetivo de RNF3. La medición debe repetirse en el hardware de referencia antes de certificar la puerta G3 (media propuesta <= 1 s y percentil 99 <= 2.5 s).

### 8.5 Aislamiento de particiones (INT-01 a INT-05)

Las pruebas automáticas confirman que: la partición de 200 sujetos estratificados produce 140/30/30 y es determinista e independiente del orden; la asignación de un sujeto a dos particiones, la alteración del manifiesto sellado y el ajuste de un escalador con sujetos ajenos a `train` generan `DataLeakageError`; la partición site-wise no comparte centros; y los estadísticos de normalización coinciden con los de `train` aunque `test` contenga valores extremos.

### 8.6 Validación de metadatos

El esquema `config/metadata_schema.json` se valida con un registro conforme y con 10 casos de incumplimiento (frecuencia de muestreo de 100 Hz, ADC de 12 bits, impedancia de 60 kOhm, desfase de 50 ms, deriva de 10 ppm, incertidumbre de 11 ms, identificadores mal formados, banda de edad inválida, rechazo de 35 % sin revisión y campo no declarado), todos rechazados; además se verifican las reglas cruzadas (`primary_lead`, coherencia del conteo de ventanas y comparador sin norma documentada).

Las 41 pruebas de `tests/test_phase2_pipeline.py` se superaron en la fecha de edición, incluida la prueba de la cadena completa a 125 Hz.

### 8.7 Comportamiento de las características sobre ventanas reales a 125 Hz

Sobre las 1 109 ventanas aceptadas de la muestra de ondas:

| Característica | Media +- DE | P5 - P95 | Máximo | Observación |
|---|---|---|---|---|
| Duración del QRS (ms) | 90 +- 15 | 72 - 112 | 212 | Plausible |
| Intervalo PR (ms) | 213 +- 46 | 144 - 264 | 264 | El máximo coincide con el límite de búsqueda; el 6.5 % de las ventanas cae en ese límite |
| Intervalo QT (ms) | 365 +- 86 | 223 - 505 | 707 | Dispersión alta para ritmo sinusal |
| QTc de Bazett (ms) | 423 +- 96 | 247 - 622 | 785 | Ídem |

A 125 Hz cada muestra equivale a 8 ms. Esa resolución limita la exactitud de la duración del QRS y de la pendiente máxima dV/dt (hallazgo H-10), y la delineación de la onda P y de la onda T muestra saturación y dispersión (PR y QT). Se recomienda tratar PR, QT, QTc y dV/dt como características de baja fiabilidad en la Fase 3 y evaluar su aporte con y sin ellas. Las tasas de valores indefinidos son: entropía muestral 39.8 % de las ventanas (secuencia RR demasiado corta), el resto de las características de variabilidad 4.9 % (menos de tres latidos válidos), PR 4.2 % y QT/QTc 0.1 %; VLF es constante en ventanas de 10 s (sin información) y se excluye del análisis de correlación. La concordancia del detector de picos R con las anotaciones de PulseDB es F1 = 1.00 en mediana.

---

## 9. Criterios de aceptación del DQR y hallazgos abiertos

### 9.1 Criterios para la firma del DQR (puerta G1 y afines)

| N.º | Criterio | Umbral | Resultado en PulseDB | Estado |
|---|---|---|---|---|
| 1 | Pérdida global neta de señal | < 15 % de las horas adquiridas | 46.7 % (muestra de 41 sujetos) | **No cumple** |
| 2 | Cuotas de distribución de PAS y PAD | >= 5 % en cada rango crítico (cohorte y partición de prueba) | Cohorte: falla PAD >= 100 mmHg (0.65 %); prueba: falla PAS >= 160 (4.7 %) y PAD >= 100 (0.86 %) | **No cumple** |
| 3 | Comparador certificado | 100 % de sesiones con norma de validación documentada | Sin certificado por sesión (monitores hospitalarios) | No cumple / no evaluable |
| 4 | Sincronización | >= 95 % de ciclos con incertidumbre <= 10 ms; desfase < 50 ms | 99.7 % de las ventanas con desfase `ABP_Lag` > 50 ms | **No cumple** |
| 5 | Metadatos conformes | 100 % de registros válidos frente al esquema | Mapeo de PulseDB al esquema pendiente de ejecutar sobre todas las sesiones | Pendiente |
| 6 | Equidad y representatividad | Sección 6.4 | Solo edad, sexo y fuente; sin raza, etnia ni comorbilidades | No cumple / limitación |
| 7 | Rechazo no selectivo | Cociente entre subgrupos <= 1.5 o justificación clínica | Edad 2.02; estrato de PAS 1.61 | **No cumple** |
| 8 | Umbrales congelados | Calibrados con `train`/`val` y registrados antes de consultar `test` | Sin congelar; el pSQI del plan requiere revisión | Pendiente |

**Conclusión.** Con los datos y umbrales actuales el DQR **no se puede firmar**. Los incumplimientos son hallazgos, no fallos del software: indican que (i) la compuerta pSQI debe rediseñarse, (ii) la distribución de presión de PulseDB no cubre los extremos diastólicos altos, y (iii) el supuesto de sincronización S3 no lo garantiza la fuente. Se recomienda a los tres responsables decidir si la Fase 3 se inicia con un alcance de uso restringido o si se incorpora una fuente adicional.

### 9.2 Hallazgos abiertos

| N.º | Hallazgo | Acción propuesta | Responsable |
|---|---|---|---|
| H-1 | Margen estrecho del pSQI sobre el umbral 0.50 con señal limpia | Calibración con datos reales y análisis de sensibilidad por subgrupo | Rocha, Hidalgo |
| H-2 | El filtrado causal desplaza PR (-19 ms en promedio) y QT (-21 ms) frente a fase cero en señal sintética | Entrenar y desplegar con la misma cadena causal; evaluar con datos reales el corte y el orden del pasa-altos | Rocha |
| H-3 | Baja fiabilidad de VLF y LF en ventanas de 10-30 s | Tratar como descriptores de baja fiabilidad; comparar el desempeño con y sin ellos en la Fase 3 | Rocha |
| H-4 | Alcance de ANSI/AAMI/ISO 81060-2 para un estimador continuo sin manguito | Decidir sobre ISO 81060-3 e IEEE 1708 | Buitrago |
| H-5 | Umbrales numéricos de cuotas demográficas no fijados en el plan | Ratificar los valores propuestos (sección 6.2) | Hidalgo |
| H-6 | Semántica del pareado ECG-referencia con comparadores oscilométricos intermitentes | Definir la ventana de ECG asociada a cada lectura | Buitrago |
| H-7 | Valores numéricos de las cuotas de la norma parametrizados a partir del plan | Contrastar con el texto vigente de la norma licenciada | Buitrago |
| H-8 | El umbral de pSQI (0.50) coincide con la mediana poblacional en PulseDB y explica el 99 % de los rechazos; el rechazo se concentra en >= 65 años (70.8 %) y PAS >= 160 mmHg (67.3 %) | Rediseñar el índice de calidad espectral y recalibrar con `train`/`val` (sección 5.5) | Rocha, Hidalgo |
| H-9 | PulseDB solo conserva segmentos con buena concordancia PPG-presión (`PPG_ABP_Corr` >= 0.90): sesgo de selección aguas arriba | Declarar como limitación; no extrapolar el desempeño a señales de peor calidad | Buitrago |
| H-10 | Resolución de 8 ms a 125 Hz limita QRS, dV/dt, PR y QT; PR satura en 264 ms | Tratarlas como características de baja fiabilidad; validar con anotaciones o con una fuente a mayor frecuencia | Rocha |
| H-11 | Las correlaciones más altas con la presión (|rho| hasta 0.37) son de textura y amplitud del QRS, sensibles a ganancia y posición del electrodo | Vigilar confusión por instrumento y normalizar por sujeto | Rocha |
| H-12 | Desfase `ABP_Lag` de cientos de milisegundos con cambios de signo dentro del mismo sujeto | Confirmar su definición con la documentación de PulseDB y con los autores; no asumir sincronización | Rocha, Buitrago |
| H-13 | La frecuencia de red detectada (50 Hz en VitalDB) no coincide con la esperada (60 Hz) | Verificar el origen y el diseño del notch | Rocha |
| H-14 | Licencias: ODbL (MIMIC) y CC BY-NC-SA 4.0 (VitalDB); población hospitalaria; sin postura, medicación ni comorbilidades | Revisión legal antes de cualquier uso comercial; declarar el alcance de uso | Hidalgo |

---

## 10. Aprobación

El DQR se firma únicamente cuando los criterios de la sección 9.1 están en estado "Cumple" o cuando el equipo acepta expresamente, por escrito, el alcance restringido correspondiente. **En esta edición el estado es "no firmable"** (véase la conclusión de 9.1) y las firmas se dejan en blanco. Las cifras de las secciones 3 a 6 son un diagnóstico preliminar del corpus, no una certificación.

| Nombre | Rol | Alcance de la aprobación | Firma | Fecha |
|---|---|---|---|---|
| Juan Manuel Buitrago | Validación Clínica y Criterios Hemodinámicos | Sección 3: admisibilidad hemodinámica y certificación de etiquetas maestras | ______________________ | ____ / ____ / ________ |
| Luis Carlos Rocha | Infraestructura, Algoritmos TI y Preprocesamiento | Secciones 2, 4, 7 y 8: estadísticas, saturación, visualizaciones y latencia | ______________________ | ____ / ____ / ________ |
| German Alberto Hidalgo | Ética Médica, Privacidad y Control de Calidad | Secciones 5 y 6: balance de rechazo y equidad demográfica | ______________________ | ____ / ____ / ________ |

| Versión | Fecha | Descripción |
|---|---|---|
| 1.0.0 | 2026-09-19 | Primera edición de la Fase 2, previa a la ingesta de datos reales. |
| 1.1.0 | 2026-09-20 | Incorporación de resultados reales de PulseDB v2.0 (catálogo completo y muestra de 41 sujetos), mínimo de muestreo de 125 Hz y hallazgos H-8 a H-14. Puertas no firmadas. |
