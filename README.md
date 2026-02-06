# Especificación WMIBO v1.0
### Formato nativo de SATX (y como contrato estable para `wmibo` solver). 

[SATX: Modelado y Decisión Formal en Sistemas Wicked - SAT, #SAT, Weighted MaxSAT y MIP](https://www.academia.edu/145768932/SATX_Modelado_y_Decisi%C3%B3n_Formal_en_Sistemas_Wicked_SAT_SAT_Weighted_MaxSAT_y_MIP)

---

# WMIBO v1.0 — SATX Native Hybrid Optimization Format

**Estado:** Stable v1.0
**Propósito:** representar una teoría operacional híbrida con variables booleanas, enteras y reales; restricciones hard/soft; activaciones; objetivos; y consultas (solve/query).
**Archivo:** `*.wmibo` (UTF-8; ASCII recomendado)

## 1. Modelo semántico (qué significa un archivo WMIBO)

Un archivo WMIBO describe un problema sobre el dominio mixto:

* Booleanas: $b \in {0,1}^{B}$
* Enteras: $i \in \mathbb{Z}^{I}$ con cotas explícitas
* Reales: $r \in \mathbb{R}^{R}$ con cotas o libres

Define:

* **Hard constraints**: deben cumplirse siempre.
* **Soft constraints**: pueden violarse pagando una penalidad $w$.
* **Indicadores**: activan (o desactivan) restricciones lineales en función de un literal booleano.
* **Objetivo**: minimización/maximización de una función lineal + penalidades de soft.

### 1.1 Interpretación de variables en lineales

* En expresiones lineales, una variable booleana `bK` se interpreta como un entero $b_K \in {0,1}$.
* Una variable entera `iK` es $i_K \in [L,U]\cap\mathbb{Z}$.
* Una real `rK` es $r_K \in [L,U]\subseteq\mathbb{R}$ o libre.

### 1.2 Semántica de soft (definición canónica v1.0)

Toda restricción soft $R_j$ con peso $w_j>0$ se entiende como:

* existe un “indicador de violación” implícito $v_j \in {0,1}$,
* $v_j=0 \Rightarrow R_j$,
* objetivo agrega $w_j \cdot v_j$.

**En v1.0**, solo se exige soft **para cláusulas** (CNF/WCNF). Soft lineales/PB quedan reservadas para v1.1+ (pero el formato deja ganchos).

---

## 2. Conformidad (niveles)

* **WMIBO-CORE v1.0:** `cnf`, `wcnf`, `obj`, `var`, `opt`.
* **WMIBO-MIP v1.0:** CORE + `lin` + `ind`.
* **WMIBO-QUERY v1.0:** MIP + `query` (recomendado aunque sea opcional en solver).

---

## 3. Léxico y reglas generales

### 3.1 Comentarios y espacios

* Comentario: una línea que comienza con `c` o `#` (ignoradas).
* Espacios: separador por uno o más espacios o tabs.
* Líneas vacías: ignoradas.
* El archivo es **line-oriented**: cada directiva ocupa una línea.

### 3.2 Identificadores

* `ID`: `[A-Za-z_][A-Za-z0-9_]*`
* Los IDs son **case-sensitive**.

### 3.3 Números

* `INT`: entero decimal con signo opcional.
* `NUM`: `INT` o flotante (incluye notación científica).
* Pesos `w`: `UINT64` (decimal sin signo, recomendado).

### 3.4 Variables y literales

* Variable booleana: `b<k>` con `1 ≤ k ≤ B`
* Variable entera: `i<k>` con `1 ≤ k ≤ I`
* Variable real: `r<k>` con `1 ≤ k ≤ R`
* Literal booleano: `b<k>` o `~b<k>`

---

## 4. Estructura del archivo

### 4.1 Header (obligatorio)

```
p wmibo 1 <B> <I> <R> [<NC> <NL> <NIND>]
```

* `1` es la versión de formato (WMIBO v1.0).
* `B,I,R` son obligatorios.
* `NC, NL, NIND` son contadores declarativos (opcionales; el parser puede ignorarlos o usarlos como sanity check).

### 4.2 Bloques

Los bloques se delimitan así:

```
begin <block>
  ...
end
```

Bloques v1.0:

* `cnf`  (cláusulas hard/soft sin peso explícito)
* `wcnf` (cláusulas hard/soft con peso explícito)
* `lin`  (restricciones lineales con ID)
* `ind`  (indicadores: literal => constraint ID)
* `obj`  (objetivo)
* `opt`  (opciones; puede ser bloque o líneas sueltas)
* `query` (consultas; recomendado)

Fuera de bloques se permiten: `var`, `opt`, y comentarios.

---

## 5. Declaración de variables (recomendado)

Líneas `var` pueden aparecer fuera de bloques (y opcionalmente dentro de un bloque `vars` si lo agregas luego; v1.0 no lo requiere).

### 5.1 Sintaxis

```
var b <k> [0,1] [name=<ID>]
var i <k> bin [name=<ID>]
var i <k> [<L>,<U>] [name=<ID>]
var r <k> free [name=<ID>]
var r <k> [<L>,<U>] [name=<ID>]
```

### 5.2 Semántica

* Si una variable no se declara, su dominio por defecto es:

  * `b`: [0,1]
  * `i`: [0,0] (no recomendado) **o** [0,10] (NO; evitar defaults ambiguos).
    **Regla v1.0:** enteras y reales **deben declararse** si aparecen en lin/obj. (Los solvers pueden ser más permisivos, pero el formato v1.0 lo exige).
  * `r`: `free` (tampoco recomendado como default)

---

## 6. CNF y WCNF

### 6.1 Bloque `cnf`

Cláusula:

```
cl hard <lit>... 0
cl soft <lit>... 0
```

* `cl hard` es hard CNF.
* `cl soft` es soft CNF de **peso 1** (con penalidad implícita).

### 6.2 Bloque `wcnf`

Cláusula ponderada:

```
wcl <w> soft <lit>... 0
wcl <w> hard <lit>... 0
```

* `soft` penaliza con peso `w`.
* `hard` ignora `w` o lo conserva como metadata; semánticamente es hard.

### 6.3 Reglas de validez

* Una cláusula debe terminar con literal `0`.
* Se permite cláusula vacía: `cl hard 0` (infeasible inmediato).
* Literales deben referir `bK` válidos.

---

## 7. Restricciones lineales (`lin`)

### 7.1 Sintaxis

```
lc <CID> <= <rhs> : <coef> <var> <coef> <var> ...
lc <CID> >= <rhs> : ...
lc <CID> =  <rhs> : ...
```

Donde:

* `<CID>` es un `ID` único en todo el archivo (namespace global de constraints).
* `<coef>` es `NUM`.
* `<var>` es `bK | iK | rK`.

Ejemplo:

```
lc C1 <= 4 : 1 r1 2 i1 -3 b2
```

### 7.2 Semántica y normalización

* `<=` se toma directo.
* `>=` se normaliza multiplicando por (-1): `-expr <= -rhs`.
* `=` se descompone en dos: `expr <= rhs` y `-expr <= -rhs`.

**Nota:** v1.0 define que la parte lineal es *lineal real*; el integrality entra por el dominio de `iK` y `bK`.

---

## 8. Indicadores (`ind`) — regla v1.0 (importante)

### 8.1 Sintaxis

```
ind <lit> => <CID>
```

### 8.2 Semántica v1.0 (un activador por restricción)

Cada `CID` puede tener **a lo sumo un indicador**.

* Si existe `ind p => C`, entonces la restricción `C` está **activa** si y solo si `p` es verdadera.
* Si no existe indicador para `C`, entonces `C` está **siempre activa**.

### 8.3 Conflictos (norma v1.0)

Es **error de formato** si:

* aparecen dos líneas `ind ... => <mismo CID>` con literales distintos, o
* aparece repetida con literal distinto por negación.

Esto es deliberado: v1.0 prefiere una semántica simple y no ambigua.
(En v1.1+ se puede permitir `ind (p OR q) => C` con un bloque nuevo.)

---

## 9. Objetivo (`obj`)

### 9.1 Sintaxis

```
obj min : lin <coef> <var> <coef> <var> ...
obj max : lin <coef> <var> ...
```

* En v1.0 solo hay **un objetivo lineal**.
* Las penalidades de soft CNF/WCNF se consideran **automáticamente** parte del objetivo total.

### 9.2 Semántica

El solver minimiza/maximiza:

$$
\text{ObjLin}(b,i,r) + \sum_{j\in\text{soft}} w_j\cdot v_j
$$

donde (v_j) es el indicador implícito de violación de la restricción soft (j).

---

## 10. Opciones (`opt`)

Línea:

```
opt <key> <value>
```

Claves recomendadas v1.0:

* `feas_tol` (NUM) tolerancia de factibilidad para lineales
* `int_tol`  (NUM) tolerancia de integridad
* `time_limit` (NUM, segundos)
* `node_limit` (INT)
* `seed` (UINT)

El CLI del solver puede sobreescribir.

---

## 11. Consultas (`query`) — recomendado

WMIBO v1.0 reserva un bloque `query` para describir lo que se quiere ejecutar.

### 11.1 Sintaxis propuesta v1.0

```
begin query
  solve feas
  solve opt
end
```

Extensiones compatibles (pueden existir aunque solver no las implemente aún):

```
  query count proj b1 b2 b7
  query explain mus
```

**Regla de formato:** un archivo puede tener cero o más `solve/query`.
Si no hay `query`, el comportamiento por defecto sugerido es `solve opt` si hay `obj` o soft; si no, `solve feas`.

---

## 12. Salidas recomendadas (contrato solver)

* Factible/óptimo:

  * `s OPTIMUM FOUND` o `s SATISFIABLE` (si es solo feas)
  * `o <valor>` (si aplica)
  * `v ...` asignaciones para `b`, `i`, `r` (formato libre pero estable)
* Infeasible:

  * `s INFEASIBLE` (o `s UNSATISFIABLE` para logic-only)
* Unbounded:

  * `s UNBOUNDED`
* Parada por límite:

  * `s UNKNOWN` y `o <best_or_nan>`

---

## 13. Ejemplos mínimos

### 13.1 SAT puro (CNF hard)

```text
p wmibo 1 3 0 0
begin cnf
  cl hard b1 ~b2 0
  cl hard b2 b3 0
end
begin query
  solve feas
end
```

### 13.2 Weighted MaxSAT (WCNF soft)

```text
p wmibo 1 2 0 0
begin wcnf
  wcl 5 soft b1 0
  wcl 1 soft b2 0
  wcl 1 hard b1 b2 0
end
begin query
  solve opt
end
```

### 13.3 MIP con indicador

```text
p wmibo 1 1 1 1
var i 1 [0,5]
var r 1 [0,10]
begin cnf
  cl hard b1 0
end
begin lin
  lc C1 <= 4 : 1 r1 1 i1
end
begin ind
  ind b1 => C1
end
begin obj
  obj min : lin 1 r1 2 i1
end
begin query
  solve opt
end
```

---

## 14. Reglas de compatibilidad y futuro

* La versión (`p wmibo 1 ...`) permite introducir v1.1+ con:

  * indicadores compuestos,
  * soft lineales/PB,
  * objetivos múltiples,
  * bloque `proof/trace`.
* Un parser v1.0 **debe**:

  * rechazar versiones mayores si no se declara compatibilidad,
  * ignorar comentarios y líneas vacías,
  * fallar con error claro ante `ind` conflictivos o IDs duplicados.

---

## 15. Checklist de validación v1.0

Un archivo v1.0 es válido si:

* Existe exactamente un header `p wmibo 1 ...`
* Referencias `bK/iK/rK` respetan rangos B/I/R
* Cada `lc CID ...` define un ID único
* Cada `ind ... => CID` refiere a un `CID` existente
* Cada `CID` tiene 0 o 1 indicador
* Cada cláusula termina en `0`
* Si aparecen enteras/reales en `lin/obj`, existen `var i/var r` correspondientes (regla recomendada para portabilidad)

---

© Oscar Riveros. Todos los derechos reservados.

---
