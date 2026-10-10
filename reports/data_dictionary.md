# Diccionario de Datos y Especificación de Variables del Sistema AASIM

**Proyecto:** AASIM - Software como Dispositivo Médico (SaMD) para la estimación continua de PAS, PAD y PAM a partir de derivaciones de electrocardiografía
**Fase:** 2 - Preparación de Datos, Gobernanza y Mitigación de Riesgos de Validez
**Documento:** `reports/data_dictionary.md`, versión 1.1.0
**Fecha de edición:** 20 de septiembre de 2026
**Esquema formal asociado:** `config/metadata_schema.json` (JSON Schema 2020-12, `schema_version = 1.1.0`)

| Área | Responsable | Contribución a este documento |
|---|---|---|
| Validación Clínica | Juan Manuel Buitrago | Variables de referencia, rangos hemodinámicos admisibles, reglas de sincronización con el comparador (RF3, R3, S1) |
| Ingeniería TI | Luis Carlos Rocha | Series temporales, características, tipos de datos, integridad referencial y marco de versionado de datos |
| Ética y Pacientes | German Alberto Hidalgo | Identificación y privacidad (RNF1), variables demográficas, calidad de señal (RF4) y protocolo de custodia de llaves de anonimización |

---

## 1. Propósito y alcance

Este documento especifica, campo por campo, todas las variables que circulan por el pipeline de la Fase 2: los metadatos de adquisición por sesión, las series temporales y etiquetas de presión arterial, los índices de calidad de señal, las características extraídas por ventana y las covariables demográficas codificadas. Para cada campo se declaran el tipo de dato, la unidad del Sistema Internacional (SI) o la unidad clínica de uso aceptado, el rango admisible, la obligatoriedad, las reglas de validación e integridad referencial y su trazabilidad frente a los requisitos del sistema (RF1-RF4, RNF1-RNF4).

Las definiciones aquí contenidas son normativas para el código de `src/` y para el esquema `config/metadata_schema.json`; cualquier discrepancia entre ambos y este documento se trata como un defecto de Fase 2 y se resuelve conforme a la sección 11 (versionado).

### 1.1 Convenciones

| Símbolo | Significado |
|---|---|
| **O** | Obligatorio en todo registro. |
| **C** | Condicional: obligatorio si se cumple la condición indicada en la regla de validación. |
| **Op** | Opcional. |
| Unidades | SI cuando existe; mmHg para presión arterial (unidad clínica de uso aceptado, 1 mmHg = 133.322 Pa); mV para tensión bioeléctrica; kOhm para impedancia; ppm para deriva de reloj. |
| `NaN` | Valor no determinable en una ventana (por ejemplo, QT cuando hay menos de tres latidos delineables). No se imputa. |
| Rango admisible | Intervalo de **plausibilidad fisiológica o instrumental**. Un valor fuera de rango genera una marca de plausibilidad y revisión, salvo que la regla indique exclusión automática. |

### 1.2 Códigos de trazabilidad

RF1: procesamiento y extracción de características en tiempo real. RF2: estimación de PAS, PAD y PAM a partir de ECG. RF3: comparación contra dispositivo de referencia certificado. RF4: advertencia de mala calidad y suspensión de la inferencia. RNF1: confidencialidad, seudonimización y protección de datos. RNF2: latencia de extremo a extremo menor o igual a 5 s. RNF3: hardware accesible y de costo razonable. RNF4: robustez ante variabilidad de impedancia y electrodo. Riesgos R1-R4 y supuestos S1-S4 conforme al plan de la Fase 1.

---

## 2. Módulo 1 - Procedencia, trazabilidad y privacidad

| Campo | Tipo | Unidad | Rango / formato admisible | Oblig. | Regla de validación e integridad referencial | Requisitos |
|---|---|---|---|---|---|---|
| `schema_version` | Cadena (SemVer) | - | Constante `1.1.0` | O | Debe coincidir con `$id` del esquema vigente; un valor distinto implica revalidación completa. | RNF1 |
| `subject_id` | Cadena alfanumérica | - | `^SUBJ-[0-9]{5}$` | O | Clave primaria opaca del paciente. Se asigna por permutación aleatoria; **no se deriva de dato identificable alguno**. Único en toda la base. Es la unidad de partición patient-wise. | RNF1, R2 |
| `recording_id` | Cadena alfanumérica | - | `^REC-[0-9]{7}$` | O | Único por sesión. Clave foránea hacia `subject_id` (una sesión pertenece a un solo sujeto; un sujeto puede tener varias sesiones, todas en la misma partición). | RF1, RF3 |
| `dataset_version` | Cadena (SemVer) | - | `^[0-9]+\.[0-9]+\.[0-9]+$` | O | Versión de la base consolidada; se rige por la sección 11. | RF1 |
| `site_id` | Cadena alfanumérica | - | `^SITE-[0-9]{3}$` | O | Código opaco del centro. Unidad de la partición site-wise; todo `subject_id` pertenece a un único `site_id`. | RNF1, R2, S4 |
| `source_institution` | Cadena | - | 2-120 caracteres | O | Institución de origen ya seudonimizada. No se admiten nombres de servicios, médicos ni ubicaciones geográficas más finas que la institución. | RNF1 |
| `anonymization_protocol` | Enumeración | - | `HIPAA_SAFE_HARBOR`, `GDPR_PSEUDONYMISATION`, `HIPAA_SAFE_HARBOR_AND_GDPR_PSEUDONYMISATION` | O | Estándar aplicado antes de incorporar el registro al entorno de desarrollo. Nota: el campo se denomina también `anonymization_standard` en la directiva operativa; el nombre normativo es el del esquema. | RNF1 |
| `custody_key_status` | Enumeración | - | `pseudonymised_key_retained`, `destroyed_irreversible` | O | Estado de la tabla de correspondencia (sección 12). Solo `destroyed_irreversible` autoriza a denominar el registro "anonimizado"; en el otro caso el registro es "seudonimizado". | RNF1 |

---

## 3. Módulo 2 - Parámetros técnicos de adquisición

| Campo | Tipo | Unidad | Rango / formato admisible | Oblig. | Regla de validación e integridad referencial | Requisitos |
|---|---|---|---|---|---|---|
| `ecg_sampling_frequency_hz` | Número | Hz | 125 a 20 000 | O | Mínimo 125 Hz (criterio ratificado por el equipo en la versión 1.1.0 para admitir PulseDB, cuya frecuencia nativa es 125 Hz; las adquisiciones propias deberían mantener 250 Hz o más). Toda ventana se procesa a la frecuencia nativa declarada; el filtro pasa-bajos (45 Hz) y las bandas de los SQI exigen `fs > 90 Hz` con margen. A 125 Hz la resolución temporal es de 8 ms, lo que limita la exactitud de la duración del QRS y de `dV/dt` (véase el riesgo V-18 del informe de riesgos). | RF1, RNF4 |
| `adc_resolution_bits` | Entero | bit | 16 a 32 | O | Mínimo 16 bits. Define la cuantización mínima usada en la tasa de saturación. | RF1, RNF4 |
| `adc_full_scale_mv` | Número | mV | > 0 | Op | Rango pico a pico del ADC. Requerido para calcular `saturation_rate_percentage` en unidades físicas. | RF4, RNF4 |
| `sensor_hardware_model` | Cadena | - | 2-120 caracteres | O | Referencia del sensor. Permite auditar variabilidad entre dispositivos. | RNF3 |
| `leads_utilized` | Arreglo de enumeración | - | `I, II, III, aVR, aVL, aVF, V1-V6`; 1 o más, sin repetidos | O | Se prioriza la derivación II. | RF1, RF2 |
| `primary_lead` | Enumeración | - | Igual que arriba | O | **Regla cruzada:** debe pertenecer a `leads_utilized` (verificada en `metadata_validation.py`). | RF1, RF2 |
| `lead_contact_impedance_kohm` | Número | kOhm | 0 a 50 | O | Impedancia electrodo-piel tolerada; no debe superar 50 kOhm. Valores superiores se rechazan en el esquema. | RNF4, R1 |
| `mains_frequency_hz` | Entero | Hz | 50 o 60 | O | Frecuencia nominal de red del sitio; inicializa la búsqueda del notch adaptativo (`filters.estimate_mains_frequency`). | RF1, R1 |
| `recording_duration_s` | Número | s | > 0 | Op | Duración total; base del cómputo de horas adquiridas para la pérdida neta de señal. | RF1 |

---

## 4. Módulo 3 - Contexto demográfico y fisiológico

Todas las variables de este módulo son datos personales de salud o cuasi-identificadores. Se almacenan con el mínimo nivel de detalle necesario (principio de minimización de RNF1): no se registran fecha de nacimiento, edad exacta, talla, peso ni fechas absolutas.

| Campo | Tipo | Unidad | Rango / formato admisible | Oblig. | Regla de validación e integridad referencial | Requisitos |
|---|---|---|---|---|---|---|
| `age_bracket` | Enumeración | años | `18-29, 30-39, 40-49, 50-59, 60-69, 70-79, 80-89, 90+` | O | Estrato decenal. La categoría `90+` agrupa edades extremas para evitar reidentificación (Safe Harbor). Para el escalado numérico se usa el punto medio del estrato. | R2, S4 |
| `biological_sex` | Enumeración | - | `female, male, intersex` | O | Sexo biológico. Se codifica con One-Hot. | R2, S4 |
| `bmi_category` | Enumeración | kg/m² | `underweight, normal, overweight, obese_class_1, obese_class_2, obese_class_3, not_available` | O | Clasificación OMS. `not_available` se usa cuando la fuente no aporta talla y peso (MIMIC en PulseDB). Para el escalado numérico se usa un valor representativo por categoría; `not_available` se imputa con 22.0 kg/m² y se marca con el indicador `bmi__not_available`. | R2, RNF4 |
| `posture` | Enumeración | - | `supine, seated, standing, ambulatory, not_available` | O | Postura durante el trazado (`not_available` si la fuente pública no la registra). Modifica la presión hidrostática y el tono autonómico; se usa como factor de ajuste. Las lecturas de referencia y el ECG deben compartir la misma postura. | RF2, RF3 |
| `active_cardiovascular_medication` | Arreglo de enumeración | - | `beta_blocker, ace_inhibitor, arb, calcium_channel_blocker, diuretic, other_cardiovascular, unknown` | O | Lista vacía significa sin medicación. `unknown` es excluyente (si aparece, `maxItems = 1`). Codificación multi-hot. | RF2, R2 |
| `known_arrhythmias` | Arreglo de enumeración | - | `atrial_fibrillation, atrial_flutter, ventricular_ectopy, conduction_block, other, unknown` | O | Lista vacía significa sin arritmias conocidas; `unknown` es excluyente. La presencia de fibrilación o flúter invalida las suposiciones de ritmo sinusal de los descriptores HRV; se reporta en el DQR por separado. | RF2, R2 |
| `hypertension_status_baseline` | Enumeración | - | `normal, elevated, stage_1, stage_2, hypertensive_crisis, unknown` | Op | Clasificación AHA/ACC basal, usada para la auditoría de cuotas y para la estratificación de la partición. | R2, S4 |
| `comorbidities` | Arreglo de enumeración | - | `diabetes, vascular_stiffness, intraventricular_conduction_disorder, chronic_kidney_disease` | Op | Categorías gruesas para la auditoría de subgrupos protegidos. Ampliar el catálogo exige incremento MENOR del esquema. | R2, S4 |

---

## 5. Módulo 4 - Referencia y sincronización metrológica

| Campo | Tipo | Unidad | Rango / formato admisible | Oblig. | Regla de validación e integridad referencial | Requisitos |
|---|---|---|---|---|---|---|
| `reference_device_type` | Enumeración | - | `oscillometric_brachial_automatic, invasive_intra_arterial_line, volume_clamp` | O | Tecnología del comparador. Determina la semántica temporal de la etiqueta (continua o intermitente). | RF3, R3 |
| `reference_device_model` | Cadena | - | 2-120 caracteres | O | Marca y modelo. | RF3, S1 |
| `reference_measurement_uncertainty_mmhg` | Número | mmHg | 0 a 20 | O | Incertidumbre metrológica declarada. Insumo del piso de error irreducible (riesgo V-06 del informe de riesgos). | R3, S1 |
| `reference_validation_standard` | Enumeración | - | `ANSI_AAMI_ISO_81060-2, ANSI_AAMI_ISO_81060-3, IEEE_1708, none_documented` | O | Norma con la que se validó el comparador. **Regla:** `none_documented` es admisible en el esquema pero bloquea la certificación del registro en el DQR (S1). | RF3, S1 |
| `sync_protocol` | Enumeración | - | `PTP, NTP, hardware_trigger, manual_event_alignment` | O | Mecanismo de sincronización de relojes. `manual_event_alignment` exige verificación por correlación de eventos. | S3, R1 |
| `sampling_offset_ms` | Número | ms | 0 a < 50 | O | Retardo temporal absoluto medido entre las dos señales. Estrictamente inferior a 50 ms. | S3, RF3 |
| `max_timestamp_uncertainty_ms` | Número | ms | 0 a 10 | O | Incertidumbre máxima de marca temporal por ciclo. Los ciclos con incertidumbre superior a 10 ms se descartan automáticamente. | S3 |
| `clock_skew_tolerance_ppm` | Número | ppm | 0 a < 10 | O | Deriva máxima de reloj tolerada. A 10 ppm la deriva acumulada alcanza 10 ms en 1 000 s, lo que fija el intervalo máximo de resincronización (ver informe de riesgos, V-05). | S3 |

---

## 6. Módulo 5 - Control de calidad de la grabación

| Campo | Tipo | Unidad | Rango / formato admisible | Oblig. | Regla de validación e integridad referencial | Requisitos |
|---|---|---|---|---|---|---|
| `n_windows_total` | Entero | ventanas | >= 0 | Op | Número de ventanas evaluadas en la sesión. | RF4 |
| `n_windows_rejected` | Entero | ventanas | >= 0 | Op | **Regla cruzada:** menor o igual a `n_windows_total`; corresponde al conteo de `quality_flag = 1`. | RF4 |
| `rejection_ratio_percentage` | Número | % | 0 a 100 | O | **Regla cruzada:** coincide con `100 * n_windows_rejected / n_windows_total` con tolerancia de 0.1 puntos porcentuales. | RF4, R4 |
| `mean_bsqi_score` | Número | adimensional | 0 a 1 | O | Promedio del bSQI de la sesión. | RF4 |
| `mean_ksqi_score` | Número | adimensional | >= 0 | Op | Promedio de la curtosis fisiológica. | RF4 |
| `mean_psqi_score` | Número | adimensional | 0 a 1 | Op | Promedio de la potencia espectral relativa. | RF4 |
| `saturation_rate_percentage` | Número | % | 0 a 100 | Op | Fracción de muestras en los rieles del ADC (`quality_assessment.saturation_fraction`). | RF4, RNF4 |
| `qc_review_required` | Booleano | - | `true`/`false` | O | **Regla condicional del esquema:** si `rejection_ratio_percentage` > 30, debe ser `true` (auditoría clínica individualizada). | RF4, R4 |

---

## 7. Series temporales, ventanas y etiquetas

Estos campos describen las tablas de trabajo generadas por el pipeline (una fila por muestra o por ventana según se indica). No forman parte del esquema JSON de metadatos, pero sus claves foráneas dependen de él.

| Campo | Tipo | Unidad | Rango / formato admisible | Oblig. | Regla de validación e integridad referencial | Requisitos |
|---|---|---|---|---|---|---|
| `timestamp_rel_ms` | Entero positivo | ms | >= 0 | O | Tiempo relativo al inicio de la sesión. Estrictamente monótono creciente; sin fechas absolutas (Safe Harbor). | RF1, S3 |
| `ecg_raw_lead_ii` | Punto flotante | mV | Depende de `adc_full_scale_mv`; típico -5 a +5 | O | Señal cruda de la derivación II. Nunca se sobrescribe (sección 11). No se aceptan `NaN` fuera de discontinuidades declaradas. | RF1 |
| `ecg_filtered` | Punto flotante | mV | Típico -5 a +5 | O | Salida de `filters.apply_filter_chain` en modo **causal** para todo dato destinado a entrenamiento e inferencia. El modo de fase cero solo se admite en auditoría retrospectiva y debe declararse en el registro de procedencia del artefacto. | RF1, R1 |
| `window_id` | Cadena | - | `recording_id` + `:` + índice de ventana | O | Único. Clave foránea hacia `recording_id`. | RF1 |
| `window_start_ms`, `window_end_ms` | Entero | ms | Diferencia entre 10 000 y 30 000 | O | Duración de ventana entre 10 y 30 s. Las ventanas nunca cruzan fronteras de sesión ni de sujeto. | RF1, RNF2 |
| `partition` | Enumeración | - | `train, val, test` | O | Heredada del sujeto (`split_dataset.assign_windows`). Un `subject_id` tiene exactamente una partición. | R2, RNF1 |
| `quality_flag` | Booleano | - | 0 válido, 1 rechazo | O | Salida de la compuerta RF4. Si es 1, no se calcula ninguna estimación de presión arterial. | RF4, R4 |
| `sqi_composite` | Punto flotante | adimensional | 0 a 1 | O | Promedio de `min(1, índice/umbral)` para bSQI, kSQI y pSQI. Vale 1.0 si y solo si los tres criterios se cumplen. | RF4 |
| `ref_systolic_bp` | Punto flotante | mmHg | 70 a 240 | C | Obligatoria en la partición de entrenamiento, validación y prueba; ausente en inferencia. Se censura fuera de rango (`censor_reference_labels`). | RF3, S1 |
| `ref_diastolic_bp` | Punto flotante | mmHg | 40 a 140 | C | Ídem. Debe cumplir `ref_systolic_bp - ref_diastolic_bp >= 20`. | RF3, S1 |
| `ref_mean_bp` | Punto flotante | mmHg | 50 a 180 (referencial) | C | Medida por el comparador; si no está disponible, `PAD + (PAS - PAD) / 3` y se marca `ref_mean_bp_derived = true`. | RF2, RF3 |
| `ref_label_valid` | Booleano | - | `true`/`false` | O | Resultado de la censura hemodinámica. | RF3, S1 |
| `ref_exclusion_reason` | Enumeración | - | `admisible, valor no finito, PAS fuera de rango, PAD fuera de rango, PAS <= PAD, presión de pulso inferior al mínimo, presión de pulso superior al máximo` | O | Códigos 0-6 de `filters.REASON_LABELS`. | RF3, R3 |
| `ref_unstable_flag` | Booleano | - | `true`/`false` | Op | Marca de inestabilidad de la referencia (variación de PAS superior a 15 mmHg en 120 s en reposo, `flag_unstable_reference`). | R3, S1 |
| `sync_uncertainty_ms` | Punto flotante | ms | 0 a 10 | C | Incertidumbre temporal del par ECG-referencia; ciclos con más de 10 ms se descartan. | S3 |

---

## 8. Índices de calidad de señal y características por ventana

### 8.1 Índices de calidad (compuerta RF4)

| Campo | Tipo | Unidad | Rango admisible | Umbral de aceptación | Definición y regla | Requisitos |
|---|---|---|---|---|---|---|
| `bsqi` | Punto flotante | adimensional | 0 a 1 | >= 0.85 | F1 de latidos coincidentes entre Pan-Tompkins y el detector de longitud de curva, tolerancia 50 ms. Cero si ninguno detecta latidos. | RF4, R4 |
| `ksqi` | Punto flotante | adimensional | >= 0 | >= 5.0 | Curtosis de Pearson (gaussiana = 3) en bloques de 5 s, agregada con la mediana. Ruido incoherente tiende a 3; saturación produce valores subgaussianos. | RF4, R4 |
| `psqi` | Punto flotante | adimensional | 0 a 1 | >= 0.50 | Potencia en 5-15 Hz dividida por la potencia en 1-40 Hz (Welch). | RF4, R4 |
| `ssqi` | Punto flotante | adimensional | - | Informativo | Asimetría (tercer momento estandarizado); no interviene en la compuerta. | RF4 |
| `n_beats_pan_tompkins`, `n_beats_curve_length` | Entero | latidos | >= 0 | - | Latidos de cada detector; su cociente audita el bSQI. | RF4 |
| `failed_criteria` | Lista de cadenas | - | subconjunto de `bSQI, kSQI, pSQI, no_finito` | - | Causa del descarte, que se comunica al usuario. | RF4, R4 |
| `saturation_fraction` | Punto flotante | fracción | 0 a 1 | Propuesta: <= 0.01 por sesión (a ratificar) | Fracción de muestras en los rieles del ADC. | RF4, RNF4 |
| `flatline_fraction` | Punto flotante | fracción | 0 a 1 | Reporte | Fracción de la señal en tramos planos de 0.5 s o más. | RF4, RNF4 |

Regla de la compuerta: `quality_flag = 0` si y solo si `bsqi >= 0.85`, `ksqi >= 5.0` y `psqi >= 0.50`; en cualquier otro caso `quality_flag = 1`.

### 8.2 Características morfológicas del ECG (clase 1)

| Campo | Unidad | Rango de plausibilidad | Definición | Requisitos |
|---|---|---|---|---|
| `feat_pr_interval_ms` | ms | 60 a 400 | Inicio de la onda P a inicio del QRS; mediana de latidos. `NaN` si la onda P no se detecta. | RF2 |
| `feat_qrs_duration_ms` | ms | 40 a 200 | Inicio a fin del complejo QRS por umbral de pendiente. | RF2 |
| `feat_qt_interval_ms` | ms | 200 a 650 | Inicio del QRS a fin de la onda T (método de la tangente). | RF2 |
| `feat_qtc_bazett_ms` | ms | 250 a 700 | `QT / sqrt(RR)`, RR en s (RR previo). | RF2 |
| `feat_qtc_fridericia_ms` | ms | 250 a 700 | `QT / RR^(1/3)`, RR en s. | RF2 |
| `feat_dvdt_max` | mV/s | > 0 | Pendiente máxima ascendente de la onda R (unidades de ECG por segundo). Correlaciona con contractilidad. | RF2 |
| `feat_s_depth_mv` | mV | -3 a 0.5 | Profundidad de la onda S respecto de la línea isoeléctrica. | RF2 |
| `feat_st_deviation_mv` | mV | -1 a 1 | Desviación del segmento ST a 60 ms del fin del QRS. | RF2 |
| `feat_r_amplitude_mv` | mV | 0.1 a 5 | Amplitud de la onda R sobre la línea isoeléctrica. | RF2, RNF4 |
| `feat_t_amplitude_mv` | mV | -2 a 2 | Amplitud de la onda T (con signo). | RF2 |

Los valores se calculan en unidades físicas; la normalización robusta se aplica aguas abajo y solo con estadísticos de entrenamiento.

### 8.3 Variabilidad de la frecuencia cardíaca (clase 2)

| Campo | Unidad | Rango de plausibilidad | Definición | Requisitos |
|---|---|---|---|---|
| `feat_hrv_mean_nn_ms` | ms | 300 a 2 000 | Promedio de intervalos NN aceptados. | RF2 |
| `feat_hrv_sdnn_ms` | ms | 0 a 500 | Desviación estándar de NN (ddof = 1). | RF2 |
| `feat_hrv_rmssd_ms` | ms | 0 a 500 | Raíz de la media cuadrática de diferencias sucesivas. | RF2 |
| `feat_hrv_pnn50_pct` | % | 0 a 100 | Porcentaje de diferencias sucesivas mayores a 50 ms. | RF2 |
| `feat_hrv_vlf_ms2` | ms² | >= 0 | Potencia 0.0033-0.04 Hz. **Baja fiabilidad en ventanas menores a 250 s.** | RF2 |
| `feat_hrv_lf_ms2` | ms² | >= 0 | Potencia 0.04-0.15 Hz. Fiabilidad limitada en ventanas cortas. | RF2 |
| `feat_hrv_hf_ms2` | ms² | >= 0 | Potencia 0.15-0.40 Hz. | RF2 |
| `feat_hrv_lf_hf` | adimensional | >= 0 | Cociente LF/HF; `NaN` si HF = 0. | RF2 |
| `feat_hrv_sd1_ms`, `feat_hrv_sd2_ms` | ms | >= 0 | Semiejes de la elipse de Poincaré. | RF2 |
| `feat_hrv_sampen`, `feat_hrv_apen` | adimensional | 0 a 3.5 | Entropía muestral y aproximada (m = 2, r = 0.2 DE). `NaN` si no hay coincidencias. | RF2 |

Los intervalos RR fuera de 300-2 000 ms o desviados más de 20 % de la mediana local se excluyen y **no se interpolan**. Se exigen al menos 8 intervalos NN válidos; en caso contrario toda la clase HRV queda en `NaN`.

### 8.4 Paquetes wavelet Daubechies 4 (clase 3)

Con nivel de descomposición `L = 4` (configurable) se obtienen `2^L = 16` subbandas ordenadas por frecuencia, cada una de ancho `fs / 2^(L+1)` Hz.

| Campo | Cantidad | Rango | Definición | Requisitos |
|---|---|---|---|---|
| `feat_wpd_e_00` ... `feat_wpd_e_15` | 16 | [0, 1]; suman 1 | Energía relativa de la subbanda. | RF2 |
| `feat_wpd_h_00` ... `feat_wpd_h_15` | 16 | [0, 1] | Entropía de Shannon normalizada de la distribución de energía de los coeficientes de la subbanda. | RF2 |
| `feat_wpd_entropy_total` | 1 | [0, ln 16] | Entropía wavelet de la distribución de energía entre subbandas. | RF2 |

### 8.5 Texturas GLCM en regiones de interés (clase 4)

El espectrograma (STFT, ventana de Hann de 192 ms, salto de 16 ms, `nfft = 256`) se expresa en escala logarítmica y se cuantiza a 16 niveles con los percentiles 1-99 de la propia ventana. Las ROI son: complejo QRS (10-30 Hz, ±60 ms alrededor de R) y onda T (1-7 Hz, de 150 a 400 ms después de R). Las matrices de co-ocurrencia (distancia 1; 0°, 45°, 90° y 135°) se acumulan entre latidos.

| Campo | Cantidad | Rango | Definición | Requisitos |
|---|---|---|---|---|
| `feat_glcm_qrs_contrast`, `feat_glcm_t_contrast` | 2 | 0 a 225 | Contraste. | RF2 |
| `feat_glcm_qrs_correlation`, `feat_glcm_t_correlation` | 2 | -1 a 1 | Correlación; `NaN` si la varianza es nula. | RF2 |
| `feat_glcm_qrs_energy`, `feat_glcm_t_energy` | 2 | (0, 1] | Raíz cuadrada del ASM. | RF2 |
| `feat_glcm_qrs_homogeneity`, `feat_glcm_t_homogeneity` | 2 | (0, 1] | Homogeneidad. | RF2 |
| `feat_glcm_qrs_asm`, `feat_glcm_t_asm` | 2 | (0, 1] | Momento angular de segundo orden. | RF2 |

El vector completo tiene **65 características** con el orden fijado por `extract_features.feature_names()`. Los tiempos de cómputo por etapa se reportan en `FeatureResult.latency_ms` (RNF2).

---

## 9. Covariables codificadas para el modelado

| Columna generada | Origen | Codificación | Ajuste | Requisitos |
|---|---|---|---|---|
| `age_years_mid` | `age_bracket` | Punto medio del estrato, escalado robusto (mediana, IQR) | Solo con entrenamiento | RF2, R2 |
| `bmi_representative` | `bmi_category` | Valor representativo por categoría, escalado robusto | Solo con entrenamiento | RF2, RNF4 |
| `sex__female`, `sex__male`, `sex__intersex` | `biological_sex` | One-Hot con categorías fijas del esquema | No aplica | RF2, R2 |
| `posture__supine`, `posture__seated`, `posture__standing`, `posture__ambulatory`, `posture__not_available` | `posture` | One-Hot con categorías fijas | No aplica | RF2 |
| `med__beta_blocker`, `med__ace_inhibitor`, `med__arb`, `med__calcium_channel_blocker`, `med__diuretic`, `med__other_cardiovascular`, `med__unknown` | `active_cardiovascular_medication` | Multi-hot | No aplica | RF2 |
| `bmi__not_available` | `bmi_category` | Indicador binario de IMC imputado | No aplica | RF2, R2 |

Una categoría fuera del esquema lanza un error (no crea una columna nueva), de modo que la dimensión de entrada no depende del contenido de los conjuntos de validación o prueba.

---

## 10. Reglas de integridad referencial y de dominio transversales

| ID | Regla | Verificación | Consecuencia del incumplimiento |
|---|---|---|---|
| INT-01 | `subject_id` es único y cada `recording_id` referencia exactamente un `subject_id`. | Validador de esquema y pruebas de partición | Rechazo del registro |
| INT-02 | Todos los registros y ventanas de un `subject_id` pertenecen a una sola partición. | `assign_windows`, `assert_no_cross_partition_subjects` | `DataLeakageError` |
| INT-03 | Los conjuntos `train`, `val` y `test` tienen intersección vacía de sujetos, verificada sobre identificadores y huellas SHA-256 con sal. | `assert_disjoint_subjects` | `DataLeakageError` |
| INT-04 | En la partición site-wise, ningún `site_id` aparece en más de una partición. | `assert_disjoint_sites` | `DataLeakageError` |
| INT-05 | Los estadísticos de normalización (mediana, IQR, escalado de covariables, pesos de estrato) se ajustan solo con filas de `train`. | `TrainOnlyRobustScaler.fit`, `assert_scaler_train_only` | `DataLeakageError` |
| INT-06 | `timestamp_rel_ms` es estrictamente creciente dentro de cada `recording_id`. | Verificación de ingesta | Rechazo de la sesión |
| INT-07 | `primary_lead` pertenece a `leads_utilized`. | `metadata_validation.validate_metadata` | Rechazo del registro |
| INT-08 | `rejection_ratio_percentage` es coherente con los conteos de ventanas. | `metadata_validation.validate_metadata` | Rechazo del registro |
| INT-09 | Si `rejection_ratio_percentage` > 30, `qc_review_required = true`. | Esquema (condicional `if/then`) | Rechazo del registro |
| INT-10 | Ninguna etiqueta de referencia se usa como entrada de característica; `ref_mean_bp` derivado no puede entrar al conjunto de predictores. | Revisión de esquema de características (`feature_names`) | Bloqueo de la Fase 3 |
| INT-11 | Cada ventana usa solo muestras de ECG anteriores o iguales al instante de su etiqueta (ventana de cola). | Revisión de código y pruebas de causalidad | Bloqueo de la Fase 3 |

---

## 11. Marco de versionado de datos (dirección: Luis Carlos Rocha)

### 11.1 Principios

1. **Inmutabilidad de lo crudo.** Los archivos de `data/raw/` no se modifican ni se sobrescriben; toda corrección genera un artefacto derivado en `data/processed/` con su propia versión.
2. **Trazabilidad completa.** Cada artefacto derivado registra: versión del conjunto de datos de origen, huella SHA-256 de cada archivo de entrada, versión del esquema, versión del código (identificador de confirmación del repositorio), parámetros de configuración (`FilterConfig`, `SQIThresholds`, `FeatureConfig`, `SplitConfig` con su semilla) y modo de filtrado (causal o fase cero).
3. **Reproducibilidad.** La misma versión de datos, de código y de configuración produce byte a byte el mismo resultado; las particiones son deterministas (hash SHA-256 de `semilla:sujeto`) e independientes del orden de las filas.
4. **Separación de particiones.** El manifiesto de partición se sella (`seal_manifest`) y su huella se publica en el registro de versiones; una modificación posterior lo invalida (`verify_seal`).

### 11.2 Política de numeración semántica (`MAYOR.MENOR.PARCHE`)

| Componente | Se incrementa cuando... | Ejemplo | Efecto sobre los resultados aguas abajo |
|---|---|---|---|
| MAYOR | Cambia el esquema de forma incompatible, se altera la definición de una etiqueta o de una característica, se modifica la política de censura o de partición. | Cambiar el límite de PAS de censura | Todo modelo y reporte previo queda obsoleto y debe recalcularse |
| MENOR | Se incorporan sujetos, sesiones o campos opcionales nuevos sin alterar los existentes. | Ingesta de un nuevo centro | Recalcular particiones si cambia la cohorte; los sujetos previos conservan su partición |
| PARCHE | Se corrigen errores de formato o metadatos que no alteran señales ni etiquetas. | Corrección tipográfica de `sensor_hardware_model` | Ninguno |

**Regla de estabilidad de particiones.** Al añadir sujetos (incremento MENOR) los sujetos ya asignados **conservan** su partición; los nuevos se asignan por el mismo mecanismo determinista. Un sujeto jamás cambia de partición entre versiones, porque ello contaminaría los conjuntos de prueba ya evaluados.

### 11.3 Registro de cambios y puertas de publicación

Toda versión se publica con: notas de cambio, lista de huellas de archivos, resultado de la validación de esquema (porcentaje de registros válidos), certificado de aislamiento (`SplitCertificate`) y resumen del DQR. Una versión no se publica si el porcentaje de registros que validan contra el esquema es inferior al 100 % o si el certificado de aislamiento no pudo emitirse.

---

## 12. Protocolo de custodia de llaves de anonimización (dirección: German Alberto Hidalgo)

### 12.1 Distinción entre seudonimización y anonimización

El identificador `subject_id` es un código opaco asignado por permutación aleatoria sin derivación desde datos personales; por sí solo no permite reidentificar al paciente. Mientras exista una tabla de correspondencia entre el identificador original y `subject_id`, el conjunto de datos es **seudonimizado** en el sentido del RGPD (artículo 4, numeral 5): reversible para quien custodia la tabla y, por tanto, sigue sujeto a la normativa de protección de datos. Solo tras la **destrucción verificada** de la tabla y de toda copia el conjunto puede considerarse **anonimizado de forma irreversible**, y únicamente entonces `custody_key_status` toma el valor `destroyed_irreversible`.

### 12.2 Roles

| Rol | Responsabilidad | Restricción |
|---|---|---|
| Custodio de llaves (dirección de Ética y Pacientes) | Genera, custodia y destruye la tabla de correspondencia; autoriza toda reidentificación excepcional. | No tiene acceso de escritura al repositorio de código ni a los modelos. |
| Custodio suplente | Ejerce el control dual con el custodio principal. | Designado por el comité de ética institucional; distinto de los integrantes de ingeniería. |
| Equipo de ingeniería (Ingeniería TI) | Procesa exclusivamente datos ya seudonimizados. | Sin acceso a la tabla ni a las llaves, ni a los sistemas donde se almacenan. |
| Validación Clínica | Puede solicitar una reidentificación clínica excepcional (por ejemplo, un hallazgo incidental relevante). | Toda solicitud se tramita ante el custodio y queda registrada. |

### 12.3 Ciclo de vida de la llave

| Etapa | Requisito |
|---|---|
| Generación | La permutación y cualquier sal criptográfica se generan con un generador criptográficamente seguro. Los identificadores no se derivan de números de historia clínica, documentos ni fechas. |
| Almacenamiento | La tabla se cifra con AES-256 y se almacena en un repositorio físicamente y lógicamente separado del entorno de desarrollo, con control de acceso por doble autorización (conocimiento dividido entre dos custodios). |
| Uso | Solo se accede a la tabla para la asignación inicial de identificadores y para reidentificaciones autorizadas. Cada acceso se registra (quién, cuándo, motivo, autorización); el registro es de solo anexado. |
| Copias | Se prohíben copias no inventariadas. Todas las copias autorizadas figuran en el inventario del custodio. |
| Rotación | Ante sospecha de compromiso se declara incidente, se notifica al comité de ética y se evalúa la reasignación de identificadores (incremento MAYOR de `dataset_version`). |
| Congelamiento | Al cerrar la Fase 2 (versión candidata a la Fase 3), el comité decide si la finalidad del estudio aún exige conservar la tabla. |
| Destrucción | Si no hay finalidad que justifique conservarla, se destruye la tabla y todas sus copias mediante borrado criptográfico (destrucción de la clave de cifrado) y sobrescritura de los medios. Se levanta un acta firmada por ambos custodios con las huellas de los medios afectados. Solo entonces se actualiza `custody_key_status`. |

### 12.4 Controles de desidentificación previos a la incorporación (RNF1)

| Control | Aplicación |
|---|---|
| Identificadores directos | Eliminación de nombres, documentos, contactos, números de historia clínica, direcciones y cualquier identificador biométrico distinto del propio ECG. |
| Fechas | Sustitución por tiempo relativo (`timestamp_rel_ms`); no se conservan fechas absolutas de atención. |
| Edad | Estratos decenales; las edades de 90 años o más se agrupan en `90+`. |
| Geografía | Solo el código opaco del centro (`site_id`); nada más fino. |
| Riesgo de reidentificación por combinación | Antes de cualquier informe o compartición se verifica que cada combinación de covariables (edad, sexo, centro, comorbilidad) tenga al menos 5 sujetos; las celdas menores se suprimen o se agrupan. |
| ECG como dato biométrico | La morfología del ECG es casi identificadora; el registro de señal cruda solo se comparte bajo acuerdo de uso de datos y nunca junto con la tabla de correspondencia. |

### 12.5 Marco normativo de referencia

El protocolo se elabora tomando como referencia el método Safe Harbor de HIPAA y el RGPD. Para el contexto colombiano deben confirmarse con el comité de ética institucional los requisitos aplicables de la Ley 1581 de 2012 (protección de datos personales) y de la Resolución 8430 de 1993 (investigación en salud). Este documento no constituye asesoría jurídica; la interpretación de la normativa es responsabilidad de la instancia institucional competente.

---

## 13. Matriz de trazabilidad requisito - campos

| Requisito | Campos y módulos principales |
|---|---|
| RF1 | `ecg_raw_lead_ii`, `ecg_filtered`, `timestamp_rel_ms`, `window_*`, `ecg_sampling_frequency_hz`, `adc_resolution_bits`, todas las `feat_*` |
| RF2 | Todas las `feat_*`, covariables codificadas, `posture`, `active_cardiovascular_medication`, `known_arrhythmias` |
| RF3 | `ref_*`, `reference_*`, `sync_protocol`, `sampling_offset_ms`, `max_timestamp_uncertainty_ms`, `clock_skew_tolerance_ppm`, `ref_label_valid`, `ref_unstable_flag` |
| RF4 | `quality_flag`, `sqi_composite`, `bsqi`, `ksqi`, `psqi`, `ssqi`, `failed_criteria`, `saturation_fraction`, módulo 5 completo |
| RNF1 | `subject_id`, `recording_id`, `site_id`, `anonymization_protocol`, `custody_key_status`, `age_bracket`, sección 12 |
| RNF2 | `FeatureResult.latency_ms`, `benchmark_latency`; `window_start_ms`/`window_end_ms` (ventanas de 10-30 s) |
| RNF3 | `sensor_hardware_model`, dependencias limitadas a NumPy, SciPy y PyWavelets |
| RNF4 | `lead_contact_impedance_kohm`, `saturation_rate_percentage`, `flatline_fraction`, `feat_r_amplitude_mv`, normalización robusta mediana/IQR |
| R1 | `mains_frequency_hz`, cadena de filtros de `filters.py` |
| R2, S4 | `age_bracket`, `biological_sex`, `bmi_category`, `hypertension_status_baseline`, `comorbidities`, `partition`, estratos de PAS |
| R3, S1 | `reference_measurement_uncertainty_mmhg`, `reference_validation_standard`, `ref_unstable_flag` |
| R4 | `quality_flag`, `failed_criteria`, mensajes al usuario |
| S3 | `sampling_offset_ms`, `sync_uncertainty_ms`, `clock_skew_tolerance_ppm` |

---

## 14. Correspondencia con PulseDB v2.0 (fuente de datos de la Fase 2)

**Dirección:** Luis Carlos Rocha (mapeo técnico) y German Alberto Hidalgo (privacidad). La fuente pública PulseDB v2.0 (MIMIC-III y VitalDB; 5 361 sujetos y 5 245 454 segmentos de 10 s a 125 Hz) se incorporó mediante `src/ingestion/pulsedb_catalog.py` y `src/ingestion/pulsedb_sample.py`. La tabla siguiente indica qué campo del diccionario se puede poblar y cuáles no.

| Campo del diccionario | Origen en PulseDB | Estado |
|---|---|---|
| `subject_id` | Permutación aleatoria (`SUBJ-xxxxx`); nombre original solo en la tabla de correspondencia restringida | Disponible |
| `site_id` | `SITE-001` (MIMIC), `SITE-002` (VitalDB) | Disponible (solo dos centros) |
| `age_bracket` | `Subj_Age` (edad exacta, agrupada en bandas decenales) | Disponible |
| `biological_sex` | `Subj_Gender` | Disponible (femenino, masculino) |
| `bmi_category` | `Subj_BMI` solo en VitalDB | Parcial: `not_available` en MIMIC (0 % de disponibilidad) |
| `ecg_sampling_frequency_hz` | 125 Hz (fija) | Disponible; cumple el mínimo de 125 Hz de la versión 1.1.0 |
| `ref_sbp_mmhg`, `ref_dbp_mmhg` | `SegSBP`, `SegDBP` (presión arterial invasiva) | Disponible |
| `sampling_offset_ms` | `ABP_Lag` (muestras x 8 ms), cuya definición debe confirmarse | Disponible con reservas (véase el DQR, sección 3.3) |
| `posture`, `active_cardiovascular_medication`, `known_arrhythmias`, `comorbidities`, `hypertension_status_baseline` | No incluidos | No disponible (`not_available` o `unknown`) |
| `lead_contact_impedance_kohm`, `sensor_hardware_model`, `adc_resolution_bits`, `adc_full_scale_mv`, `mains_frequency_hz` | No incluidos (ECG normalizado por PulseDB) | No disponible |
| `reference_measurement_uncertainty_mmhg`, `reference_validation_standard`, `sync_protocol`, `max_timestamp_uncertainty_ms`, `clock_skew_tolerance_ppm` | No incluidos | No disponible |

**Consecuencia para la puerta G4.** Varios campos obligatorios del esquema 1.1.0 (impedancia, modelo de sensor, resolución del ADC, incertidumbre del comparador, norma de validación, protocolo de sincronización, incertidumbre temporal y deriva de reloj) no se pueden poblar con datos reales de PulseDB sin inventar valores, y el equipo decidió no hacerlo. La conformidad del 100 % con el esquema queda por ello **pendiente**: se propone (Rocha, Hidalgo) un perfil de fuente pública en una versión MENOR posterior, con esos campos opcionales y un marcador explícito de origen, para no debilitar el esquema de las adquisiciones propias. En la versión 1.1.0 se añadieron las categorías `not_available` (IMC y postura) y se aceptó `unknown` en la codificación de la medicación.

**Privacidad.** Los nombres originales de PulseDB (`p000160_0`) y las marcas temporales de caso no se exportan al catálogo analítico; se guardan en `data/metadata/tabla_correspondencia_RESTRINGIDA.csv` con permisos restringidos, conforme a la sección 12. **Licencias:** ODbL (MIMIC) y CC BY-NC-SA 4.0 (VitalDB); el uso comercial requiere revisión legal (riesgo V-19).

---

## 15. Control del documento

| Versión | Fecha | Descripción | Responsables |
|---|---|---|---|
| 1.0.0 | 2026-09-19 | Primera edición para la Fase 2, alineada con `metadata_schema.json` 1.0.0 y los módulos de `src/`. | Buitrago, Rocha, Hidalgo |
| 1.1.0 | 2026-09-20 | Mínimo de muestreo del ECG en 125 Hz; categorías `not_available`; codificación de `unknown` en medicación; sección 14 de correspondencia con PulseDB v2.0. Esquema 1.1.0. | Buitrago, Rocha, Hidalgo |

**Aprobación del diccionario de datos y del esquema de metadatos** (criterio 4 de las puertas hacia la Fase 3: coherencia e integridad de campos, descriptores y etiquetas de calibración).

| Nombre | Rol | Firma | Fecha |
|---|---|---|---|
| Juan Manuel Buitrago | Validación Clínica y Criterios Hemodinámicos | ______________________ | ____ / ____ / ________ |
| Luis Carlos Rocha | Infraestructura, Algoritmos TI y Preprocesamiento | ______________________ | ____ / ____ / ________ |
| German Alberto Hidalgo | Ética Médica, Privacidad y Control de Calidad | ______________________ | ____ / ____ / ________ |
