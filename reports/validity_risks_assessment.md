# Lista y Evaluación de Riesgos de Validez Metodológica y Gobernanza

**Proyecto:** AASIM - Software como Dispositivo Médico (SaMD) para la estimación continua de PAS, PAD y PAM a partir de derivaciones de electrocardiografía
**Fase:** 2 - Preparación de Datos, Gobernanza y Mitigación de Riesgos de Validez
**Documento:** `reports/validity_risks_assessment.md`, versión 1.1.0
**Fecha de edición:** 20 de septiembre de 2026
**Estado:** actualizado con los resultados de PulseDB v2.0; varias puertas de decisión **no se cumplen** (sección 8); firmas pendientes (sección 10)

| Área | Responsable | Riesgos bajo su dirección |
|---|---|---|
| Validación Clínica | Juan Manuel Buitrago | V-04, V-05 (semántica del pareado), V-06, V-15, V-17 |
| Ingeniería TI | Luis Carlos Rocha | V-01, V-02, V-03, V-05 (sincronización), V-10, V-11, V-12, V-13, V-14, V-18 |
| Ética y Pacientes | German Alberto Hidalgo | V-07, V-08, V-09, V-16, V-19 |

---

## 1. Resumen ejecutivo

El modelado de presión arterial a partir de ECG es especialmente propenso a resultados optimistas que no sobreviven al despliegue clínico. Este informe identifica diecinueve riesgos de validez, los clasifica por probabilidad y severidad, describe la salvaguarda operativa ya incorporada en el código de la Fase 2 (o el procedimiento pendiente), fija el indicador que la verifica y define las puertas de decisión para autorizar la Fase 3 (entrenamiento y optimización de modelos).

La versión 1.1.0 incorpora la primera caracterización sobre el corpus real **PulseDB v2.0** (MIMIC-III y VitalDB; 5 361 sujetos y 5 245 454 segmentos de 10 s a 125 Hz con presión arterial invasiva) y una muestra de formas de onda de 41 sujetos y 2 042 ventanas procesada con el pipeline completo. Los hallazgos principales son los siguientes.

1. **Las salvaguardas anti-fuga funcionan sobre datos reales.** La partición patient-wise 70/15/15 de 5 332 adultos (3 732/800/800) produce intersección nula de sujetos y de huellas SHA-256 y una composición prácticamente idéntica entre particiones. Con solo dos centros, la partición site-wise se sustituye por *leave-one-site-out* (V-11).
2. **La distribución de etiquetas no cubre los extremos exigidos.** La cuota de PAD >= 100 mmHg es 0.65 % (mínimo 5 %) en la cohorte admisible; en la partición de prueba la cuota de PAS >= 160 mmHg es 4.7 %. Además, VitalDB por sí sola no cumple la cuota de PAS elevada (1.9 %). El riesgo V-04 se confirma y el desempeño en la cola diastólica alta no podrá afirmarse.
3. **El supuesto S3 no está garantizado por la fuente.** El desfase de alineación que reporta PulseDB (`ABP_Lag`) supera 50 ms en el 99.7 % de las ventanas de la muestra y cambia de signo dentro de un mismo sujeto (V-05).
4. **La compuerta de calidad del plan rechaza demasiado y de forma selectiva.** El 45.7 % de las ventanas se rechaza, casi todo por pSQI (umbral 0.50, igual a la mediana poblacional); el rechazo es 70.8 % en mayores de 65 años frente a 35.0 % en menores (cociente 2.0) y 67.3 % con PAS >= 160 mmHg. No existe un umbral de pSQI que corrija a la vez la pérdida y la disparidad (V-09, V-10). El pipeline verificado funciona, pero **las puertas G1 y G8 no se cumplen**.
5. **La resolución de 125 Hz limita las características morfológicas** (PR satura en 264 ms; QRS y dV/dt con resolución de 8 ms) (V-18), y la población hospitalaria con licencias restrictivas (CC BY-NC-SA 4.0 en VitalDB) impone un alcance de uso acotado (V-19).
6. La norma ANSI/AAMI/ISO 81060-2, fijada por el plan, se refiere a esfigmomanómetros no invasivos intermitentes; el sistema AASIM es un estimador continuo sin manguito, por lo que se recomienda evaluar ISO 81060-3 e IEEE 1708 antes de la validación clínica final (V-15). Aquí la referencia además es invasiva, lo que introduce otra diferencia con el uso previsto.

Las cifras reales de este documento son un **diagnóstico preliminar** basado en una muestra pequeña de ondas; no constituyen desempeño clínico ni deben usarse para congelar umbrales.

---

## 2. Método de evaluación

### 2.1 Escalas

| Nivel | Probabilidad (P) | Severidad (S) |
|---|---|---|
| 1 | Muy improbable con las salvaguardas actuales | Sin efecto sobre la validez o solo estético |
| 2 | Improbable | Sesgo menor corregible sin repetir el estudio |
| 3 | Posible | Sesgo relevante que obliga a repetir análisis |
| 4 | Probable | Invalida una conclusión principal de desempeño |
| 5 | Casi segura sin intervención | Riesgo para el paciente o invalidación del estudio |

**Nivel de riesgo residual = P x S** evaluado **considerando efectivas solo las salvaguardas ya implementadas y verificadas en código** (las que dependen de datos reales no se cuentan como efectivas): bajo (1-6), medio (7-12), alto (13-19), crítico (20-25). Es una evaluación inicial de juicio experto; se recalibra tras el primer Data Quality Report con datos reales.

### 2.2 Cada riesgo se documenta con

Causa fisiológica o instrumental, efecto algorítmico y clínico, salvaguarda operativa (módulo y función de `src/`), indicador de verificación con umbral, responsable y estado (Implementado, Parcial, Confirmado con datos reales o Pendiente).

---

## 3. Taxonomía de fugas de información (Data Leakage)

### 3.1 Fuga por identidad inter-sujeto (Identity Leakage) - V-01

**Mecanismo.** La morfología del ECG de cada persona depende del eje eléctrico, la masa miocárdica, la conducción intraventricular y la posición de los electrodos respecto del torso. Por ello dos latidos del mismo paciente se parecen entre sí mucho más que dos latidos de pacientes distintos, y esa similitud es lo bastante estable para funcionar como una huella biométrica. Si latidos, épocas o ventanas de una misma sesión se distribuyen al azar entre entrenamiento y prueba, el modelo puede resolver la tarea por reconocimiento de identidad: aprende que "esta morfología corresponde a la presión media observada de este sujeto en entrenamiento" y la reproduce en la prueba.

**Por qué la partición aleatoria por latidos falsea el desempeño clínico.** El uso clínico real del sistema consiste en estimar la presión de un paciente **nuevo**, cuya morfología no se vio durante el desarrollo. La partición aleatoria por latidos mide, en cambio, la capacidad de interpolar entre latidos de un sujeto ya visto. Como la presión arterial de un individuo varía poco dentro de una sesión en comparación con la variabilidad entre individuos, la interpolación intra-sujeto produce un error aparente muy bajo aunque el modelo no haya aprendido ninguna relación hemodinámica generalizable. Al evaluarlo con pacientes no vistos, el error real es sustancialmente mayor. La diferencia entre ambos errores es el sesgo optimista atribuible a la fuga, y no puede corregirse a posteriori: solo se evita diseñando la partición correctamente.

**Salvaguardas implementadas.**

| Salvaguarda | Implementación |
|---|---|
| La unidad de partición es el sujeto (y el centro en datos multicéntricos), nunca el latido o la ventana. | `split_dataset.patient_wise_split`, `site_wise_split`, `hierarchical_split` |
| Asignación determinista por hash de `semilla:sujeto`, independiente del orden de las filas, con estratificación y compensación de redondeo. | `patient_wise_split` |
| Aserción criptográfica: intersección vacía de sujetos entre `train`, `val` y `test`, comprobada sobre identificadores y sobre huellas SHA-256 con sal; particiones no vacías y sin duplicados. | `assert_disjoint_subjects` (emite `SplitCertificate`) |
| Sellado del manifiesto de partición con SHA-256; cualquier modificación posterior se detecta. | `seal_manifest`, `verify_seal` |
| Verificación a nivel de ventana: todo sujeto pertenece a una sola partición. | `assign_windows`, `assert_no_cross_partition_subjects` |
| Validación cruzada interna agrupada por sujeto (para hiperparámetros dentro de `train`). | `subject_group_kfold` |
| Ajuste de estadísticos solo con `train`, con error explícito ante sujetos ajenos. | `TrainOnlyRobustScaler.fit`, `fit_transform_partitions` |

**Riesgos residuales que la partición por sujeto no elimina y su control.**

1. *Un mismo individuo registrado con dos identificadores* (por ejemplo, ingresos en centros distintos). Control: antes de la partición, la custodia (Ética y Pacientes) ejecuta una comprobación de duplicidad de identidad sobre la tabla de correspondencia, sin exponerla al equipo de ingeniería. Si se detectan duplicados se fusionan bajo un único `subject_id`.
2. *Sesiones múltiples del mismo sujeto.* Control: todas las sesiones comparten la partición del sujeto (regla INT-01/INT-02 del diccionario).
3. *Identidad a través del centro o del dispositivo* (V-11).

**Estado con PulseDB.** Se generó la partición de los 5 332 adultos del catálogo con certificado de intersección nula (huella SHA-256 del manifiesto `cbaf2aaf...b4e`); los identificadores usados son opacos (`SUBJ-xxxxx`) y la tabla de correspondencia con los nombres originales queda en acceso restringido. Dentro de cada fuente no hay nombres de archivo repetidos; la comprobación de identidad duplicada entre MIMIC y VitalDB (hospitales distintos, sin solape esperado) se documenta como pendiente de custodia.

**Prueba de detección (diagnóstico, no de aprobación).** Como comprobación independiente, en la Fase 3 se entrenará, solo con los datos de `train`, un clasificador auxiliar de identidad de sujeto sobre las características. Una exactitud de identificación muy superior al azar confirma que el vector de características contiene información de identidad; en tal caso la partición por sujeto es indispensable y la comparación de error entre validación por sujeto y validación aleatoria dentro de `train` se documenta como medida del sesgo optimista que se evitó. Esta prueba nunca utiliza los conjuntos `val` ni `test`.

### 3.2 Fuga temporal y sesgo retrospectivo (Lookahead Bias) - V-02

**Mecanismo.** Se produce cuando el valor de una característica o de una normalización asociada a un instante utiliza información posterior a ese instante. En este proyecto aparece por cuatro vías.

| Vía | Descripción | Salvaguarda |
|---|---|---|
| Filtrado no causal | `sosfiltfilt` recorre la señal hacia adelante y hacia atrás; cada muestra filtrada depende de muestras futuras. | `FilterMode.CAUSAL` por defecto; `assert_causal_for_inference` y `process_window` lanzan `NonCausalFilterError` ante el modo de fase cero; `CausalECGFilter` procesa por bloques con estado. El modo de fase cero queda reservado para auditoría retrospectiva. |
| Normalización global | Medianas, cuantiles o desviaciones calculadas sobre el registro completo (o sobre todo el conjunto) antes de particionar incorporan información futura y de los sujetos de prueba. | Normalización de señal por ventana (`robust_window_normalize`), sin memoria entre ventanas; estadísticos de características ajustados solo con entrenamiento (`TrainOnlyRobustScaler`). |
| Etiqueta centrada en la ventana | Si la ventana de ECG se centra en el instante de la lectura de presión, la mitad de la ventana es posterior a la etiqueta; el sistema en tiempo real no dispone de esa información. | Regla INT-11: las ventanas son de cola (terminan en el instante de la etiqueta o antes). El pareado se valida en la ingesta. |
| Calibración con datos de prueba | Ajustar umbrales de SQI, de censura o de filtrado observando la partición de prueba. | Todo parámetro se congela con `train` y `val`; ver V-10. |

Las funciones de extracción operan sobre una ventana ya cerrada y no comparten estadísticas entre ventanas, de modo que la cota de latencia de 5 s (RNF2) y la causalidad respecto del tiempo de la etiqueta son compatibles.

**Advertencia de consistencia entre entrenamiento y despliegue.** Si las características de entrenamiento se calculan con filtrado de fase cero y las de inferencia con filtrado causal, el modelo se entrena con una distribución distinta de la que verá en producción (V-14). La política de la Fase 2 es que **todo dato destinado a entrenamiento se procese con la misma cadena causal que el despliegue**.

### 3.3 Fuga por ventanas superpuestas en el cálculo de HRV - V-03

**Mecanismo.** Las métricas de variabilidad cardíaca se calculan sobre ventanas de 10-30 s; para densificar la muestra suelen usarse ventanas con solape. Dos ventanas que comparten muchos intervalos RR producen vectores casi idénticos. Si esas ventanas caen en particiones distintas, el modelo ve en entrenamiento una versión casi exacta de lo que se evalúa en prueba. Además, dentro de una misma partición, el solape genera dependencia estadística fuerte que sobreestima el tamaño muestral efectivo y estrecha artificialmente los intervalos de confianza.

**Salvaguardas.**

| Salvaguarda | Implementación |
|---|---|
| El sujeto completo, y con él todas sus ventanas, se asigna a una sola partición **antes** de derivar ningún parámetro de HRV; ninguna ventana puede cruzar la frontera entre particiones. | `patient_wise_split` antes de `extract_window_features`; `assign_windows` |
| La rejilla de ventanas se construye dentro de una sola grabación. | `make_window_grid` |
| Cuando se usa solape para entrenar, la validación cruzada se agrupa por sujeto. | `subject_group_kfold` |
| Al reportar intervalos de confianza y contrastes, el tamaño muestral efectivo se toma como el número de **sujetos** (o de ventanas no solapadas), y las pruebas se realizan con remuestreo por sujeto. | Procedimiento de la Fase 3 |
| Si en algún experimento se dividiera cronológicamente dentro de un sujeto (no previsto), se aplicará una separación de al menos una longitud de ventana entre bloques (purga). | Procedimiento |

### 3.4 Otras fuentes de fuga vigiladas

| Fuente | Control |
|---|---|
| Fuga de etiqueta: emplear como predictor una variable calculada a partir de PAS/PAD (por ejemplo, PAM derivada). | Regla INT-10; `feature_names()` no contiene variables de presión. |
| Ajuste de hiperparámetros o detención temprana sobre `test`. | `test` no se consulta hasta la evaluación final única; `val` es el único conjunto de selección. |
| Preprocesamiento aprendido con todo el corpus (por ejemplo, componentes principales). | Toda transformación con parámetros aprendidos se ajusta con `train` (INT-05). |

---

## 4. Matriz de riesgos y mitigaciones clínico-técnicas

| ID | Riesgo | Causa | Efecto | P | S | Nivel | Salvaguarda principal | Indicador de verificación (umbral) | Resp. | Estado |
|---|---|---|---|---|---|---|---|---|---|---|
| V-01 | Fuga por identidad inter-sujeto | Partición por latidos o ventanas; identidades duplicadas | Desempeño optimista falso | 2 | 5 | Medio (10) | Partición patient-wise, aserción criptográfica, sellado | Intersección de sujetos = 0 y de huellas = 0 (obligatorio) | Rocha | Implementado; certificado emitido con PulseDB (0 intersecciones) |
| V-02 | Sesgo retrospectivo | Filtros no causales, normalización global, etiqueta centrada | Desempeño optimista; incompatibilidad con tiempo real | 2 | 4 | Medio (8) | Modo causal por defecto, guardas, normalización local | 0 usos de fase cero en la ruta de inferencia (prueba automática) | Rocha | Implementado |
| V-03 | Superposición de ventanas HRV | Solape entre particiones o dentro de ellas | Optimismo y sobreconfianza estadística | 2 | 4 | Medio (8) | Asignación por sujeto antes de la extracción; CV agrupada | 0 ventanas en más de una partición | Rocha | Implementado |
| V-04 | Colapso hacia la media | Predominio de normotensos | El estimador no detecta hipertensión real | 4 | 5 | Crítico (20) | Estratificación, ponderación inversa, evaluación por estrato | Cuotas de la sección 3.4 del DQR: PAD >= 100 mmHg 0.65 % (mín. 5 %); prueba con PAS >= 160 mmHg 4.7 %; pendiente de calibración >= 0.8 | Buitrago | Confirmado con datos reales; mitigación parcial |
| V-05 | Desalineación temporal | Desfase y deriva de reloj entre ECG y referencia | Etiquetas asignadas al latido equivocado | 5 | 4 | Crítico (20) | Sincronización PTP/NTP, verificación por correlación, descarte por incertidumbre | Desfase < 50 ms: **99.7 % de las ventanas de PulseDB lo superan** (`ABP_Lag` de +-800 ms) | Rocha / Buitrago | Confirmado con datos reales; sin mitigación disponible en la fuente |
| V-06 | Variabilidad del comparador | Catéter arterial y monitor hospitalario; hidrostática; amortiguamiento; incertidumbre del instrumento | Ruido en la etiqueta y techo de exactitud | 4 | 4 | Alto (16) | Censura hemodinámica, promedio de lecturas estables, Bland-Altman intra-dispositivo | DE de la diferencia de la referencia estimada y reportada; en PulseDB no evaluable (sin lecturas repetidas) | Buitrago | Parcial (censura aplicada: 3.09 % excluido; `s_ref` no estimable) |
| V-07 | Sesgo demográfico | Submuestras de ancianos, obesos, diabéticos, rigidez vascular | Error desproporcionado en grupos vulnerables | 4 | 5 | Crítico (20) | Estratificación, cuotas mínimas, auditoría desagregada | Cociente de desempeño entre subgrupos (sección 6); en PulseDB solo edad, sexo y fuente son auditables | Hidalgo | Parcial: 43.5 % con 65 años o más (cumple); sin comorbilidades, raza ni etnia; IMC solo en VitalDB |
| V-08 | Falsos positivos por ruido residual | Artefactos de EMG y movimiento que simulan complejos | Estimaciones espurias, decisiones clínicas erróneas | 3 | 5 | Alto (15) | Compuerta RF4 (bSQI, kSQI, pSQI) con notificación de causa | Estimaciones emitidas con `quality_flag = 1` = 0 | Hidalgo | Implementado |
| V-09 | Sesgo de selección por rechazo de señal | El rechazo por SQI no es aleatorio: mayor en subgrupos y en rangos de presión | La muestra retenida es más joven y más normotensa que la población | 4 | 4 | Alto (16) | Reporte de rechazo por subgrupo y por estrato de PAS; umbrales por auditoría | Cociente de tasas de rechazo entre subgrupos <= 1.5: **edad 2.02; PAS 1.61** | Hidalgo | Confirmado con datos reales; no cumple |
| V-10 | Umbrales mal calibrados o ajustados con datos de prueba | Umbral pSQI = 0.50 sobre la mediana poblacional; calibración sobre `test` | Rechazo excesivo (45.7 %); fuga | 5 | 4 | Crítico (20) | Calibración solo con `train`/`val`; análisis de sensibilidad; congelamiento antes de `test` | Umbrales congelados con huella en el registro de versiones; sensibilidad exploratoria en la sección 5.5 del DQR | Rocha / Hidalgo | Confirmado con datos reales; pendiente de rediseño del índice |
| V-11 | Confusión por centro o dispositivo | El hardware o el protocolo de un centro se asocia con la etiqueta | El modelo aprende el centro, no la fisiología | 4 | 4 | Alto (16) | *Leave-one-site-out* (solo dos centros); reporte de estadísticos por centro | Desempeño en centro no visto dentro del margen acordado; las dos fuentes difieren en PAS (123.7 frente a 115.5 mmHg), rechazo (41.7 % frente a 49.9 %) y frecuencia de red detectada | Rocha | Parcial: partición site-wise 70/15/15 no realizable con 2 centros |
| V-12 | Insuficiencia muestral (S2) | Pocos sujetos o poca cobertura del espacio hemodinámico | Modelos inestables, intervalos amplios | 3 | 4 | Medio (12) | Análisis de suficiencia y cobertura antes de Fase 3 | Volumen total suficiente (5 332 adultos, 5.2 millones de segmentos); cobertura insuficiente en la cola de PAD alta y PAS >= 160 mmHg de VitalDB | Rocha | Parcial (volumen adecuado, cobertura de extremos insuficiente) |
| V-13 | HRV espectral no fiable en ventanas cortas | Resolución de 0.03-0.1 Hz en 10-30 s | Descriptores VLF/LF ruidosos y engañosos | 5 | 2 | Medio (10) | Advertencia por ventana; tratamiento como baja fiabilidad | Comparación de desempeño con y sin VLF/LF; VLF constante y entropía muestral indefinida en 39.8 % de las ventanas de 10 s | Rocha | Implementado (advertencia); confirmado |
| V-14 | Desajuste entrenamiento-despliegue | Entrenar con fase cero y desplegar con filtro causal | Sesgo sistemático de PR/QT y caída de desempeño en producción | 2 | 4 | Medio (8) | Todo dato de entrenamiento con cadena causal | Diferencia entre características causales y de fase cero reportada (sección 7.3) | Rocha | Implementado (política) |
| V-15 | Alcance de la norma de validación | ISO 81060-2 cubre dispositivos intermitentes con manguito | Criterios de aceptación no aplicables sin adaptación | 3 | 4 | Medio (12) | Evaluar ISO 81060-3 e IEEE 1708 para dispositivos continuos sin manguito | Decisión documentada de la norma de validación final | Buitrago | Pendiente |
| V-16 | Reidentificación (RNF1) | ECG casi biométrico; combinaciones de cuasi-identificadores; custodia deficiente | Violación de la confidencialidad | 2 | 5 | Medio (10) | Protocolo de custodia; k >= 5 en informes; supresión de celdas pequeñas | 0 celdas con n < 5 en reportes; acta de custodia | Hidalgo | Implementado (protocolo) |
| V-17 | Sobre-censura clínica de etiquetas | Límites de censura demasiado estrictos eliminan hipertensión o hipotensión reales | El corpus pierde precisamente los extremos de interés | 3 | 4 | Medio (12) | Reporte de exclusiones por motivo y por estrato; revisión clínica de excluidos cercanos al límite | Tasa de exclusión: 3.09 % (MIMIC 3.56 %, VitalDB 1.88 %), casi todo PAD < 40 mmHg (2.4 %); revisión de una muestra por Buitrago pendiente | Buitrago | Parcial (medido; revisión clínica pendiente) |
| V-18 | Resolución temporal insuficiente a 125 Hz | PulseDB entrega ECG a 125 Hz (8 ms por muestra); el plan pedía >= 250 Hz | QRS, dV/dt, PR y QT de baja exactitud; PR satura en 264 ms (6.5 % de ventanas) | 5 | 3 | Alto (15) | Mínimo de `sampling_rate_hz` reducido a 125 Hz con justificación; características de baja fiabilidad marcadas | Duración de QRS 90 +- 15 ms plausible; PR y QT con dispersión alta; comparación de desempeño con y sin ellas | Rocha | Confirmado con datos reales; mitigación parcial |
| V-19 | Desajuste de dominio y licencia | Población hospitalaria (cuidados intensivos y cirugía) con catéter arterial; CC BY-NC-SA 4.0 (VitalDB) y ODbL (MIMIC); sin postura, medicación ni comorbilidades | Estimaciones no extrapolables al uso ambulatorio; restricción de uso comercial | 4 | 4 | Alto (16) | Declarar el alcance de uso; revisión legal previa a uso comercial; fuente adicional con protocolo propio | Decisión documentada sobre el alcance y sobre la licencia | Hidalgo | Pendiente |

---

## 5. Análisis detallado de los riesgos hemodinámicos

### 5.1 Colapso hacia la media (Regression-to-the-Mean) - V-04

**Causa.** Las cohortes basales de acceso abierto o de voluntarios están dominadas por sujetos normotensos (PAS entre aproximadamente 110 y 130 mmHg). Un estimador entrenado para minimizar el error cuadrático medio global aprende que la apuesta más segura es predecir valores cercanos a la media de la muestra.

**Efecto.** El error global puede parecer aceptable mientras que en los extremos (hipertensión, hipotensión) el modelo subestima la desviación: las estimaciones se comprimen hacia la media y el coeficiente de regresión de la estimación sobre la referencia cae por debajo de 1. La utilidad clínica, que consiste en anticipar descompensaciones o crisis hipertensivas, se anula precisamente donde se necesita.

**Estrategias de balanceo y remuestreo (todas restringidas a `train`).**

| Estrategia | Descripción | Implementación |
|---|---|---|
| Estratificación de la partición | La asignación 70/15/15 se estratifica por estrato hemodinámico del sujeto, de modo que `val` y `test` conserven representación de los extremos. | `SplitConfig(stratify_by=...)` |
| Ponderación inversa por estrato | Peso de costo inversamente proporcional a la frecuencia del estrato de PAS (< 100, 100-119, 120-139, 140-159, >= 160), con recorte a un cociente máximo de 10 entre pesos para no amplificar ruido de etiqueta en estratos casi vacíos. Los pesos se ajustan solo con `train`. | `fit_inverse_frequency_weights`, `apply_weights` |
| Remuestreo probabilístico inverso | Sobremuestreo de sujetos y ventanas de estratos poco frecuentes **solo dentro de `train`**, ponderando por sujeto para no inflar artificialmente la dependencia intra-sujeto. | Procedimiento de la Fase 3 |
| Pérdida sensible a la cola | Penalización creciente con la distancia a la media, definida antes de observar `test`. | Procedimiento de la Fase 3 |
| Evaluación desagregada | El desempeño se reporta por estrato de PAS y no solo globalmente; `test` conserva su distribución natural y se evalúa además una versión balanceada por cuotas. | Procedimiento de la Fase 3 |

**Evidencia con PulseDB.** En el catálogo de 5 361 sujetos, la mediana de PAS es 121.9 mmHg (MIMIC) y 114.0 mmHg (VitalDB), y la mediana de PAD 60-62 mmHg. Tras la censura, el 15.3 % de las lecturas tiene PAS <= 100 mmHg y el 5.3 % PAS >= 160 mmHg (cumplen), pero solo el 0.65 % tiene PAD >= 100 mmHg (no cumple), y VitalDB por sí sola tiene 1.9 % de PAS >= 160 mmHg. La estratificación de la partición se hizo por PAS mediana del sujeto: los estratos altos son pequeños (1.9 % de los sujetos con PAS mediana >= 160 mmHg), de modo que la cola de la partición de prueba depende de pocos sujetos y de la variabilidad de lectura. Las estrategias de ponderación y remuestreo no crean información donde no la hay: con 0.65 % de lecturas de PAD alta, el desempeño en ese rango **se declarará no evaluable**, salvo que se incorpore una fuente con hipertensión diastólica.

**Criterios de detección y aceptación (propuestos, a ratificar por dirección clínica).** Pendiente de la regresión de la estimación sobre la referencia mayor o igual a 0.8 en `test`; error medio y desviación estándar reportados por cada estrato de PAS; cuotas de la etiqueta de referencia conforme a la sección 3.4 del Data Quality Report (al menos 5 % de lecturas en cada uno de los cuatro rangos críticos).

### 5.2 Desalineación temporal instrumental (Temporal Mismatch) - V-05, supuestos S3 y R1

**Causa.** El supuesto S3 establece sincronización sin desfase entre el ECG y el comparador. En la práctica ningún par de relojes cumple una sincronización perfecta: existe desfase inicial, deriva relativa (ppm) y variación (jitter) por ciclo.

**Efecto.** Una lectura de presión registrada durante un cambio de tono vascular puede asignarse a un latido de reposo previo o posterior, rompiendo la física del acoplamiento hemodinámico y creando ruido de etiqueta que no puede reducirse con más datos.

**Cuantificación de la deriva.** Con una deriva relativa de 10 ppm (límite del esquema) el desfase acumulado es de 10 ms cada 1 000 s (aproximadamente 16.7 min) y de 36 ms por hora. Como el criterio de descarte por ciclo es de 10 ms, **la resincronización debe efectuarse al menos cada 1 000 s** si el reloj opera al límite de 10 ppm; con 2 ppm el intervalo se extiende a 5 000 s. Sin resincronización periódica, una sesión de varias horas superaría el límite de 50 ms de desfase absoluto.

**Salvaguardas y verificaciones.**

| Control | Descripción |
|---|---|
| Sincronización de relojes | Protocolos PTP/NTP o disparo por hardware (`sync_protocol`). El alineamiento manual por eventos solo se admite con verificación adicional. |
| Verificación empírica del desfase | Estimación del retardo entre la serie de frecuencia cardíaca instantánea derivada del ECG y la derivada de la referencia (o el latido de la línea arterial cuando existe), mediante correlación cruzada en una ventana de búsqueda de ±500 ms; el desfase estimado se registra en `sampling_offset_ms`. |
| Descarte por incertidumbre | Todo ciclo con `sync_uncertainty_ms` > 10 ms se excluye del corpus. |
| Límites de metadatos | `sampling_offset_ms` < 50 ms y `clock_skew_tolerance_ppm` < 10 (esquema JSON). |
| Cambios bruscos | Los pares ECG-referencia tomados durante transitorios rápidos se marcan para revisión clínica. |

**Evidencia con PulseDB.** El campo `ABP_Lag` de la base (muestras a 125 Hz, 8 ms por muestra) tiene mediana de +280 ms en MIMIC y -176 ms en VitalDB, con rangos de -792 a +376 ms y de -776 a +528 ms; el 99.7 % de las 2 041 ventanas con dato supera el límite de 50 ms y, en promedio, el 27 % de las ventanas consecutivas de un mismo sujeto cambia de signo de desfase. La definición exacta del campo debe confirmarse con la documentación de la base, pero la conclusión operativa es que la fuente **no garantiza S3** y que cualquier estimador basado en tiempo de tránsito del pulso puede verse afectado por una incertidumbre de alineación de cientos de milisegundos. Por otra parte, la señal de PulseDB proviene de segmentos con correlación PPG-presión >= 0.90, lo que indica una selección previa de calidad (V-05, V-19). Se recomienda no aceptar el pareado de PulseDB como sincronizado a 50 ms y estudiar el efecto del desfase en la Fase 3 (por ejemplo, desplazando artificialmente la etiqueta) antes de interpretar el desempeño.

**Decisión clínica pendiente (Buitrago).** Con comparadores oscilométricos intermitentes, la lectura resulta de un ciclo de desinflado de decenas de segundos. Debe definirse qué ventana de ECG se empareja con esa lectura (por ejemplo, la ventana de cola que termina en la determinación de la presión sistólica). Hasta que se fije esa regla, el pareado con comparadores oscilométricos se considera provisional.

### 5.3 Variabilidad e incertidumbre metrológica del comparador - V-06, riesgo R3 y supuesto S1

**Causa.** Manguitos de tamaño inadecuado, diferencias de posición del brazo respecto del corazón, errores del operador y la propia incertidumbre del instrumento generan ruido en la etiqueta.

**Efecto: techo de exactitud.** Si la etiqueta contiene un error aleatorio de desviación estándar `s_ref` independiente del error del modelo `s_mod`, la desviación estándar observada de la diferencia entre la estimación y la referencia es `sqrt(s_mod^2 + s_ref^2)`. Ningún modelo, por bueno que sea, puede mostrar un error menor que `s_ref` frente a esa referencia, y optimizar con etiquetas ruidosas induce gradientes espurios.

**Salvaguardas.**

| Control | Descripción |
|---|---|
| Certificación del comparador (S1) | Cada sesión declara `reference_validation_standard`; `none_documented` bloquea la certificación del registro en el DQR. |
| Censura hemodinámica | Se excluyen las lecturas con PAS fuera de [70, 240] mmHg, PAD fuera de [40, 140] mmHg, PAS <= PAD o presión de pulso menor a 20 mmHg (`censor_reference_labels`). |
| Estabilidad de la referencia | Se marcan las lecturas con variación de PAS mayor a 15 mmHg en 120 s en reposo (`flag_unstable_reference`). |
| Promedio de lecturas estables | Promedio de tres lecturas secuenciales estables por sujeto en las adquisiciones oscilométricas, conforme a las pautas de la norma. |
| Estimación de `s_ref` | Diagrama de Bland-Altman con lecturas repetidas o pareadas del comparador (`generate_visualizations.plot_bland_altman`); para dos lecturas del mismo instrumento, `s_ref` = DE de las diferencias / sqrt(2). El valor se reporta y se compara con el desempeño exigido al modelo. |
| Heterocedasticidad | Se evalúa la pendiente de |diferencia| frente a la media; un error proporcional a la presión obliga a modelar la incertidumbre por nivel de presión. |

**Criterio de aceptación de referencia (propuesto).** El límite superior de concordancia de la referencia estimada debe ser compatible con el objetivo de exactitud del proyecto: `s_ref` se documenta y el objetivo de desempeño del modelo (Fase 3) se formula como error sobre la etiqueta ruidosa junto con el piso derivado de `s_ref`.

### 5.4 Sesgos demográficos y representatividad - V-07, riesgo R2 y supuesto S4

**Causa.** Submuestras de pacientes mayores de 65 años, obesos, diabéticos, con rigidez vascular o con trastornos de conducción intraventricular.

**Efecto.** El modelo puede mantener alta exactitud en individuos sanos y presentar desviaciones inaceptables en poblaciones de riesgo, produciendo desempeño desigual y potencial discriminación algorítmica.

**Evidencia con PulseDB.** El catálogo contiene 5 332 adultos (43.8 % mujeres; 43.5 % con 65 años o más) de dos hospitales (uno de cuidados intensivos y otro quirúrgico). No incluye raza, etnia, comorbilidades, medicación ni postura; el IMC existe solo para VitalDB (media 23.1). La auditoría de subgrupos protegidos queda por tanto limitada a edad, sexo y fuente, y cualquier afirmación de equidad debe restringirse a esas dimensiones. El rechazo por SQI ya muestra disparidad (70.8 % en mayores de 65 años frente a 35.0 %; 50.1 % en hombres frente a 39.9 % en mujeres; 49.9 % en VitalDB frente a 41.7 % en MIMIC), de modo que la compuerta actual introduciría un sesgo demográfico antes de entrenar (V-09).

Ver la sección 6 para el protocolo de auditoría de subgrupos.

---

## 6. Protocolo de auditoría de sesgos por subgrupos poblacionales (dirección: German Alberto Hidalgo)

### 6.1 Subgrupos protegidos y de riesgo

| Dimensión | Estratos de auditoría | Fuente en metadatos |
|---|---|---|
| Edad | 18-39, 40-64, 65-79, 80 o más | `age_bracket` |
| Sexo biológico | Femenino, masculino, intersexual (se reporta si n permite) | `biological_sex` |
| Índice de masa corporal | Bajo peso o normal, sobrepeso, obesidad clases 1-3 | `bmi_category` |
| Hipertensión basal | Normal, elevada, estadio 1, estadio 2, crisis (AHA/ACC) | `hypertension_status_baseline` |
| Comorbilidades vasculares y de conducción | Diabetes, rigidez vascular, trastorno de conducción intraventricular, enfermedad renal crónica | `comorbidities` |
| Ritmo | Sinusal, arritmias conocidas | `known_arrhythmias` |
| Medicación | Betabloqueadores, IECA, ARA-II, calcioantagonistas, diuréticos | `active_cardiovascular_medication` |
| Postura | Supina, sentada, de pie, ambulatoria | `posture` |
| Centro y dispositivo | Cada `site_id` y `sensor_hardware_model` | `site_id`, `sensor_hardware_model` |

### 6.2 Procedimiento

| Paso | Actividad | Producto |
|---|---|---|
| 1 | Comparar la composición de la cohorte con una referencia epidemiológica declarada (población objetivo del sistema) mediante diferencias estandarizadas y prueba de bondad de ajuste por dimensión. | Tabla de representatividad (S4) |
| 2 | Verificar cuotas mínimas por subgrupo (sección 6.3) y declarar como "no evaluable" todo subgrupo por debajo del mínimo, en lugar de omitirlo. | Registro de subgrupos evaluables |
| 3 | Reportar **tasa de rechazo por SQI** por subgrupo, para detectar rechazo selectivo (V-09). | Tabla de rechazo por subgrupo |
| 4 | Reportar **tasa de exclusión de etiquetas** por motivo y por subgrupo (V-17). | Tabla de exclusión |
| 5 | En la Fase 3, reportar error medio y desviación estándar de la diferencia, con intervalos de confianza obtenidos por remuestreo por sujeto, para cada subgrupo. | Ficha de equidad del modelo |
| 6 | Aplicar la puerta de decisión (sección 8): si algún subgrupo evaluable excede el umbral de disparidad, se corrige (remuestreo, ponderación, más datos) o se restringe explícitamente la indicación de uso. | Acta de decisión firmada |
| 7 | Suprimir en todo informe las celdas con menos de 5 sujetos (RNF1). | Informes conformes con la privacidad |

### 6.3 Cuotas y umbrales (propuestos)

El plan de la Fase 1 exige cuotas mínimas de muestras en adultos mayores de 65 años y en pacientes con hipertensión diagnosticada en estadios 1 o 2, sin fijar el valor numérico en el documento disponible. Se proponen los siguientes valores, que el equipo debe ratificar antes de la ingesta.

| Parámetro | Valor propuesto |
|---|---|
| Fracción mínima de sujetos de 65 años o más | 20 % de la cohorte de entrenamiento |
| Fracción mínima con hipertensión basal en estadio 1 o 2 | 25 % de la cohorte de entrenamiento |
| Número mínimo de sujetos por subgrupo para considerarlo evaluable | 30 (por debajo, se declara limitación) |
| Disparidad de desempeño: cociente entre la desviación estándar del error del subgrupo y la global | <= 1.25 |
| Disparidad de sesgo: diferencia entre el error medio del subgrupo y el global | <= 3 mmHg |
| Cociente máximo de tasas de rechazo por SQI entre subgrupos | <= 1.5 |
| Celda mínima para informar | 5 sujetos |

### 6.4 Verificación del supuesto S4

S4 se considera **no verificado** hasta que el paso 1 del procedimiento se ejecute con una referencia poblacional declarada; con PulseDB la cohorte no puede compararse con la población objetivo (ambulatoria) porque esta no se ha declarado y porque la fuente es hospitalaria. Si la cohorte disponible no representa la epidemiología de la hipertensión de la población objetivo, se declara como limitación del alcance de uso y no como propiedad del modelo.

---

## 7. Estado de la verificación funcional y resultados sobre datos reales

Las pruebas automáticas de `tests/test_phase2_pipeline.py` (41 pruebas, todas superadas en la fecha de edición) verifican con señales sintéticas de verdad-terreno conocida el comportamiento de los módulos, incluida la cadena completa a 125 Hz. **Los resultados con señal sintética no constituyen evidencia de desempeño clínico.** La sección 7.5 resume los resultados con datos reales de PulseDB.

### 7.1 Salvaguardas anti-fuga verificadas por código

| Comportamiento verificado | Resultado |
|---|---|
| La partición 70/15/15 sobre 200 sujetos estratificados produce 140/30/30 y es idéntica ante un orden aleatorio de las filas. | Cumple |
| La partición de los 5 332 adultos de PulseDB produce 3 732/800/800, con 0 intersecciones de identificadores y de huellas. | Cumple (certificado emitido) |
| La inserción de un sujeto de entrenamiento en la partición de prueba es detectada. | `DataLeakageError` |
| La alteración del manifiesto sellado es detectada. | `DataLeakageError` |
| Los estadísticos del escalador coinciden con los de `train` aunque `test` contenga valores extremos; el ajuste con sujetos ajenos a `train` falla. | Cumple |
| El modo de fase cero es rechazado en `process_window` y `assert_causal_for_inference`. | `NonCausalFilterError` |
| La compuerta RF4 no invoca la función de predicción cuando `quality_flag = 1`. | Cumple |
| El filtro causal por bloques es numéricamente idéntico al filtrado de la señal completa. | Cumple |

### 7.2 Hallazgo sobre el umbral pSQI

En 60 ventanas sintéticas limpias de 10 s la mediana del pSQI fue 0.54 con un mínimo de 0.51: el umbral de 0.50 quedaba a un margen estrecho incluso con señal limpia. **Con datos reales el hallazgo se confirma y se agrava**: la mediana de pSQI es 0.52 (MIMIC) y 0.50 (VitalDB), es decir, el umbral cae sobre la mediana; el pSQI explica 927 de 933 rechazos y en el 89 % de las ventanas rechazadas solo por pSQI la detección de picos R es correcta (F1 >= 0.9). Además, al reducir el umbral el rechazo global baja (45.7 % con 0.50; 13.2 % con 0.30), pero la disparidad por edad aumenta (cociente 2.0 con 0.50; 7.1 con 0.30). No se modifica el umbral, que es el fijado por el plan; se propone rediseñar o complementar el índice y recalibrar con `train`/`val` (V-09, V-10).

### 7.3 Hallazgo sobre el filtrado causal (V-14)

El pasa-altos causal de segundo orden a 0.5 Hz tiene un retardo de grupo de aproximadamente 132 ms a 1 Hz, 30 ms a 2 Hz y 4.6 ms a 5 Hz; el pasa-bajos de 45 Hz introduce entre 8 y 12 ms. Sobre 20 registros sintéticos de 27 s, las características obtenidas con filtrado causal frente a fase cero difirieron en promedio en -20.5 ms para el intervalo QT (máximo absoluto de 44 ms), -18.8 ms para el PR (máximo de 36 ms), +1.6 ms para la duración del QRS y -0.06 mV para la desviación del ST. Estas diferencias se deben al desplazamiento diferencial de los componentes de baja frecuencia (ondas P y T). Conclusiones para la Fase 3: (a) entrenar y desplegar con la misma cadena causal; (b) no comparar valores absolutos de QT/PR con referencias clínicas obtenidas con filtrado de fase cero sin corrección; (c) evaluar, con datos reales, una frecuencia de corte menor o un orden distinto del pasa-altos, decisión que corresponde al equipo y que requiere un incremento MAYOR de la configuración.

### 7.4 Latencia (RNF2)

Con señal sintética (contenedor de 2 CPU virtuales Intel Xeon a 2.8 GHz) el pipeline completo (filtrado, SQI y 65 características) tardó entre 0.025 s y 0.058 s por ventana de 10 a 30 s, con `fs` de 250 y 500 Hz. Con las 2 041 ventanas reales de PulseDB (10 s a 125 Hz) en el equipo de trabajo (2 CPU) la media fue 12.5 ms, la mediana 11.9 ms, el percentil 95 31.1 ms, el percentil 99 43.4 ms y el máximo 93.8 ms, lo que deja un margen mínimo de 53 veces frente al límite de 5 s. Ninguno de estos entornos es representativo del hardware objetivo de RNF3; la medición debe repetirse en el hardware de referencia antes de firmar la puerta G3.

### 7.5 Resultados sobre datos reales de PulseDB

| Aspecto | Resultado | Riesgo o puerta |
|---|---|---|
| Corpus | 5 361 sujetos; 5 245 454 segmentos; 5 332 adultos | S2 |
| Censura de etiquetas | 3.09 % excluido (MIMIC 3.56 %, VitalDB 1.88 %) | V-17 |
| Cuotas ISO tras la censura | PAS <= 100: 15.3 %; PAS >= 160: 5.3 %; PAD <= 60: 46.9 %; PAD >= 100: 0.65 % | V-04, G1 |
| Cuotas ISO en la partición de prueba | PAS >= 160: 4.7 %; PAD >= 100: 0.86 % | G1 |
| Desfase de alineación | 99.7 % de las ventanas con desfase > 50 ms | V-05, G6 |
| Rechazo global por la compuerta RF4 | 45.7 % (99 % por pSQI) | V-10, G1 |
| Rechazo por edad | 35.0 % (18-64) frente a 70.8 % (>= 65); cociente 2.02 | V-09, G8 |
| Rechazo por estrato de PAS | 41.8 % (<= 100) a 67.3 % (>= 160); cociente 1.61 | V-09, G8 |
| Pérdida global neta en la muestra | 46.7 % | G1 |
| Latencia | Media 12.5 ms; máximo 93.8 ms por ventana | G3 |
| Correlación máxima característica-presión | |rho| = 0.37 | V-04, V-14 |

---

## 8. Criterios de aceptación y puertas de decisión hacia la Fase 3

El paso a la Fase 3 (entrenamiento y optimización de modelos) exige el cumplimiento de todas las puertas siguientes. Las cuatro primeras corresponden a los criterios medibles del plan; las restantes se incorporan por los riesgos identificados en este informe.

| Puerta | Criterio | Métrica y umbral | Evidencia | Responsable | Estado |
|---|---|---|---|---|---|
| G1 | Data Quality Report firmado | Pérdida global neta de señal tras el preprocesamiento < 15 % de las horas adquiridas; distribución de etiquetas conforme a ANSI/AAMI/ISO 81060-2 con al menos 5 % de lecturas en cada uno de los cuatro rangos críticos (PAS <= 100, PAS >= 160, PAD <= 60, PAD >= 100 mmHg) | `reports/data_quality_report.md` con datos reales: pérdida 46.7 % (muestra); PAD >= 100 mmHg 0.65 %; prueba con PAS >= 160 mmHg 4.7 % | Buitrago, Rocha, Hidalgo | **No cumple** |
| G2 | Aislamiento criptográfico de particiones | Intersección nula de sujetos entre `train`, `val` y `test` (identificadores y huellas SHA-256); ningún estadístico de normalización calculado fuera de `train` | `SplitCertificate` con 0 intersecciones sobre 5 332 adultos; sello del manifiesto; `assert_scaler_train_only` | Rocha | Cumple para la partición; el escalador se verificará al ajustarlo en la Fase 3 |
| G3 | Latencia | Tiempo medio por ventana en hardware convencional con margen amplio respecto de 5 s; se propone media <= 1 s y percentil 99 <= 2.5 s | `benchmark_latency` y 2 041 ventanas reales: media 12.5 ms, percentil 99 43.4 ms, máximo 93.8 ms (equipo de trabajo, no hardware objetivo de RNF3) | Rocha | Parcial: cumple en el equipo de trabajo; pendiente hardware objetivo |
| G4 | Coherencia del diccionario y los metadatos | 100 % de los registros validan contra `metadata_schema.json` y las reglas cruzadas; todos los campos alineados con `reports/data_dictionary.md` | `metadata_validation.validate_metadata` sobre el corpus; mapeo de PulseDB descrito en el diccionario (sección 14) | Rocha, Hidalgo | Pendiente: mapeo de todas las sesiones no ejecutado |
| G5 | Certificación del comparador (S1) | 100 % de los registros con `reference_validation_standard` distinto de `none_documented` | Módulo 4 de metadatos; PulseDB no trae norma de validación por sesión | Buitrago | **No cumple** con PulseDB |
| G6 | Sincronización (S3) | Al menos 95 % de los ciclos con incertidumbre temporal <= 10 ms y desfase absoluto < 50 ms | `ABP_Lag`: 99.7 % de las ventanas con desfase > 50 ms; incertidumbre por ciclo no observable | Rocha, Buitrago | **No cumple** |
| G7 | Representatividad (S4, R2) | Cuotas y evaluabilidad de subgrupos conforme a la sección 6.3; acta de auditoría firmada | Tabla de representatividad del DQR: edad y sexo evaluables; sin raza, etnia ni comorbilidades; hipertensión basal no evaluable | Hidalgo | Parcial |
| G8 | Rechazo no selectivo (V-09) | Cociente de tasas de rechazo entre subgrupos <= 1.5, o justificación clínica documentada | DQR: edad 2.02; estrato de PAS 1.61; sexo 1.26; fuente 1.20 | Hidalgo | **No cumple** |
| G9 | Umbrales congelados (V-10) | Umbrales de SQI y de censura calibrados solo con `train`/`val`, con análisis de sensibilidad y huella registrada antes de consultar `test` | Registro de versiones; el análisis de sensibilidad de la muestra es exploratorio y no valida el congelamiento | Rocha, Hidalgo | Pendiente (rediseño del pSQI) |
| G10 | Norma de validación final (V-15) | Decisión documentada sobre la aplicabilidad de ISO 81060-2 y la incorporación de ISO 81060-3 / IEEE 1708 | Acta clínica | Buitrago | Pendiente |
| G11 | Política causal (V-02, V-14) | 0 rutas de inferencia con filtrado de fase cero; datos de entrenamiento generados con la cadena causal | Prueba automática y revisión de código | Rocha | Implementado |
| G12 | Privacidad (V-16) | Acta de custodia vigente; 0 celdas con n < 5 en informes; estado de la tabla de correspondencia declarado | Tabla de correspondencia en acceso restringido (permisos 600) fuera del catálogo analítico; celdas pequeñas agrupadas | Hidalgo | Implementado (protocolo); acta pendiente |

**Regla de decisión.** La Fase 3 se autoriza cuando todas las puertas G1-G12 están en estado "Cumple" y firmadas. Una puerta en estado "Pendiente" no se sustituye por una estimación sintética. Si G1, G2 o G5 no se cumplen, el proyecto no avanza; si G7 o G8 no se cumplen, la Fase 3 puede iniciarse únicamente con una restricción explícita del alcance de uso, aprobada por el equipo.

**Consecuencia con los datos actuales.** G1, G5, G6 y G8 no se cumplen; G2 cumple; G3, G4, G7, G9 y G10 están parciales o pendientes. Por la regla anterior, **la Fase 3 no queda autorizada** con los umbrales y la fuente actuales. Se someten a decisión del equipo tres rutas, que no se excluyen entre sí: (a) rediseñar el índice de calidad espectral y recalibrarlo con `train`/`val` para tratar G1 y G8; (b) redefinir por acta, antes de la Fase 3, el alcance de una etapa *exploratoria* de desarrollo sobre datos públicos, sin afirmaciones de desempeño clínico y con los límites de V-04, V-05 y V-19 declarados; y (c) incorporar un conjunto propio con comparador certificado y sincronización controlada (S1, S3) para la validación final. Esta decisión corresponde a Buitrago, Rocha e Hidalgo.

---

## 9. Supuestos del plan y estado de comprobación

| Supuesto | Enunciado | Estado con PulseDB | Cómo se comprobará |
|---|---|---|---|
| S1 | Registros con calidad clínica y certificación metrológica | **No se cumple según lo definido**: la referencia es presión invasiva de monitores hospitalarios, sin certificación por sesión; PulseDB conserva solo segmentos con buena concordancia PPG-presión | Auditoría de las fuentes; módulo 4 de metadatos; G5 |
| S2 | Volumen suficiente de ECG para entrenamiento supervisado | Cumple en volumen (5 332 adultos; 5.2 millones de segmentos); **insuficiente en la cola de PAD >= 100 mmHg** | Análisis de suficiencia y cobertura del espacio hemodinámico; G7 |
| S3 | Sincronización temporal sin desfase | **No se cumple**: desfase de alineación de cientos de milisegundos en el 99.7 % de las ventanas de la muestra | Verificación empírica del desfase y descarte por incertidumbre; G6 |
| S4 | Muestra representativa de la epidemiología de la hipertensión | **No verificable / no se cumple**: población hospitalaria de dos centros, sin comorbilidades ni raza | Auditoría de la sección 6; G7 |

---

## 10. Aprobación y firma metodológica

El presente informe se somete a la aprobación del equipo de la Fase 2. Con su firma, cada responsable acepta la evaluación de los riesgos bajo su dirección, las salvaguardas descritas y las puertas de decisión de la sección 8 como condiciones vinculantes para iniciar la Fase 3. **Con el estado actual de las puertas, la firma no autoriza la Fase 3**: registra la aceptación de la evaluación de riesgos y de la decisión que el equipo adopte sobre las rutas de la sección 8.

| Nombre | Rol | Alcance de la aprobación | Firma | Fecha |
|---|---|---|---|---|
| Juan Manuel Buitrago | Dirección de Validación Clínica y Criterios Hemodinámicos | Riesgos V-04, V-05 (semántica), V-06, V-15, V-17; puertas G1 (etiquetas), G5, G10 | ______________________ | ____ / ____ / ________ |
| Luis Carlos Rocha | Dirección de Infraestructura, Algoritmos TI y Preprocesamiento de Señales | Riesgos V-01, V-02, V-03, V-05, V-10 a V-14, V-18; puertas G2, G3, G4, G6, G9, G11 | ______________________ | ____ / ____ / ________ |
| German Alberto Hidalgo | Dirección de Ética Médica, Privacidad del Paciente y Control de Calidad | Riesgos V-07, V-08, V-09, V-16, V-19; puertas G7, G8, G12 | ______________________ | ____ / ____ / ________ |

Las tres firmas deben recabarse sobre la versión final de este documento; el espacio de firma permanece en blanco hasta que los responsables lo suscriban.

| Versión | Fecha | Descripción |
|---|---|---|
| 1.0.0 | 2026-09-19 | Primera edición de la Fase 2, previa a la ingesta de datos reales. |
| 1.1.0 | 2026-09-20 | Resultados reales de PulseDB v2.0; riesgos V-18 y V-19; reclasificación de V-04, V-05, V-07, V-09, V-10, V-11; estado actualizado de las puertas G1 a G12. |
