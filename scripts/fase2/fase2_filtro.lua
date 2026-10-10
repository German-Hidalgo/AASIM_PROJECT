-- Filtro de Pandoc del Proyecto AASIM (Fase 2).
-- 1) Código en línea: permite cortes de línea tras separadores de ruta e identificadores.
-- 2) Tablas: asigna anchos de columna proporcionales al contenido para evitar desbordes.

local function latex_escape(s)
  s = s:gsub("\\", "\\textbackslash{}")
  s = s:gsub("([%%&#{}])", "\\%1")
  s = s:gsub("_", "\\_")
  s = s:gsub("%$", "\\$")
  s = s:gsub("%^", "\\^{}")
  s = s:gsub("~", "\\textasciitilde{}")
  return s
end

function Code(el)
  local t = latex_escape(el.text)
  t = t:gsub("([/%.=,;:|])", "%1\\allowbreak{}")
  t = t:gsub("(\\_)", "%1\\allowbreak{}")
  return pandoc.RawInline("latex", "{\\codigo{" .. t .. "}}")
end

local function cell_len(cell)
  local n = 0
  for _, blk in ipairs(cell) do
    n = n + #pandoc.utils.stringify(blk)
  end
  return n
end

local function longest_word(cell)
  local m = 0
  for _, blk in ipairs(cell) do
    for word in pandoc.utils.stringify(blk):gmatch("%S+") do
      m = math.max(m, math.min(#word, 9))
    end
  end
  return m
end

function Table(tbl)
  local ncol = #tbl.aligns
  if ncol < 2 then return nil end
  local w, lw = {}, {}
  for i = 1, ncol do w[i] = 0; lw[i] = 0 end
  local function acc(row)
    for i = 1, ncol do
      if row[i] then
        w[i] = w[i] + math.min(cell_len(row[i]), 90)
        lw[i] = math.max(lw[i], longest_word(row[i]))
      end
    end
  end
  acc(tbl.headers)
  for _, r in ipairs(tbl.rows) do acc(r) end
  local nrows = #tbl.rows + 1
  local prop, minf, tp = {}, {}, 0
  for i = 1, ncol do
    prop[i] = math.max(w[i] / nrows, 6) ^ 0.85
    tp = tp + prop[i]
  end
  local tm = 0
  for i = 1, ncol do
    prop[i] = prop[i] / tp
    -- Ancho mínimo: la palabra más larga (en letras) debe caber sin solaparse.
    minf[i] = (lw[i] * (ncol >= 8 and 0.0082 or 0.0118)) + 0.02
    tm = tm + minf[i]
  end
  -- Reparto: cada columna recibe su mínimo y el resto se distribuye por contenido.
  local libre = math.max(1 - tm, 0)
  for i = 1, ncol do
    if tm >= 1 then
      tbl.widths[i] = minf[i] / tm
    else
      tbl.widths[i] = minf[i] + libre * prop[i]
    end
  end
  return tbl
end

function HorizontalRule()
  return pandoc.RawBlock("latex", "\\medskip\\hrule\\medskip")
end

-- Matrices anchas (8 o más columnas): página apaisada, incluyendo el encabezado previo
-- para que el título no quede huérfano en la página anterior.
function Pandoc(doc)
  local out = {}
  for _, blk in ipairs(doc.blocks) do
    if blk.t == "Table" and #blk.aligns >= 8 then
      local titulo = nil
      if #out > 0 and out[#out].t == "Header" then
        titulo = table.remove(out)
      end
      table.insert(out, pandoc.RawBlock("latex", "\\begin{landscape}"))
      if titulo then table.insert(out, titulo) end
      table.insert(out, blk)
      table.insert(out, pandoc.RawBlock("latex", "\\end{landscape}"))
    else
      table.insert(out, blk)
    end
  end
  doc.blocks = out
  return doc
end
