-- second-brain.nvim — семантический поиск по SECOND_BRAIN (JSON API на 127.0.0.1:8766)
-- Сервер: cd ~/CODES/h/second-brain && uv run second-brain --simple-http
-- В init.lua: lua require('second-brain').setup()
local M = {}
local BRAIN = vim.env.HOME .. "/SECOND_BRAIN"

local function api(path, payload, cb)
  vim.system({ "curl", "-s", "-m", "60", "-X", "POST", "http://127.0.0.1:8766" .. path,
    "-H", "Content-Type: application/json",
    "-d", vim.json.encode(payload) }, { text = true }, function(res)
    vim.schedule(function()
      if res.code ~= 0 then vim.notify("second-brain: сервер не отвечает (hub: second-brain-mcp)", vim.log.levels.ERROR) return end
      local ok, parsed = pcall(vim.json.decode, res.stdout or "")
      if not ok then vim.notify("second-brain: bad response", vim.log.levels.ERROR) return end
      cb(parsed)
    end)
  end)
end

local function open_note(fp)
  vim.cmd("edit " .. vim.fn.fnameescape(BRAIN .. "/" .. fp))
end

local function search(query)
  api("/search", { query = query, k = 12 }, function(hits)
    if #hits == 0 then vim.notify("second-brain: ничего не найдено", vim.log.levels.WARN) return end
    local items = {}
    for _, hit in ipairs(hits) do
      table.insert(items, string.format("%s :: %s [%s]", hit.file_path, hit.title or "", hit.heading_path or ""))
    end
    vim.ui.select(items, { prompt = "Second Brain: " .. query }, function(choice)
      if choice then open_note(choice:match("^(.-) :: ")) end
    end)
  end)
end

-- визуальное выделение / слово под курсором → поиск
local function search_selection()
  local mode = vim.fn.mode()
  local text
  if mode == "v" or mode == "V" then
    text = table.concat(vim.fn.getregion(vim.fn.getpos("v"), vim.fn.getpos("."), { type = mode }), " ")
  else
    text = vim.fn.expand("<cword>")
  end
  search(vim.trim(text:gsub("\n", " ")))
end

local function daily()
  local path = BRAIN .. "/daily/daily-" .. os.date("%Y-%m-%d") .. ".md"
  if vim.fn.filereadable(path) == 0 then
    local tpl = table.concat({
      "---", 'title: "Daily ' .. os.date("%Y-%m-%d") .. '"', "type: daily", "status: seedling",
      "date: " .. os.date("%Y-%m-%d"), "updated: " .. os.date("%Y-%m-%d"), "tags: [daily]",
      'moc: "[[]]"', "aliases: []", 'description: ""', "---", "",
    }, "\n")
    vim.fn.writefile(vim.split(tpl, "\n"), path)
  end
  vim.cmd("edit " .. vim.fn.fnameescape(path))
end

function M.setup(opts)
  opts = opts or {}
  vim.api.nvim_create_user_command("BrainSearch", function(o) search(o.args) end, { nargs = "+" })
  vim.api.nvim_create_user_command("BrainIndex", function()
    vim.system({ "uv", "run", "second-brain-index" }, { cwd = vim.env.HOME .. "/CODES/h/second-brain" }, function(res)
      vim.schedule(function()
        vim.notify("second-brain: " .. (res.code == 0 and (res.stdout:match("[^\n]*$") or "done") or "ошибка индексации"))
      end)
    end)
    vim.notify("second-brain: индексация запущена")
  end, {})
  vim.api.nvim_create_user_command("BrainToday", daily, {})
  vim.api.nvim_create_user_command("BrainGrep", function(o)
    vim.cmd("grep " .. vim.fn.fnameescape(o.args) .. " " .. vim.fn.fnameescape(BRAIN))
  end, { nargs = "+" })  -- обычный grep по заметкам (точные слова), результат в quickfix

  local map = function(lhs, rhs, desc)
    vim.keymap.set("n", lhs, rhs, { desc = "brain: " .. desc })
  end
  local prefix = opts.prefix or "<leader>b"
  map(prefix .. "s", function() vim.ui.input({ prompt = "Second Brain: " }, function(q) if q and q ~= "" then search(q) end end) end, "semantic search")
  map(prefix .. "w", search_selection, "search word/selection")
  map(prefix .. "i", ":BrainIndex<CR>", "reindex")
  map(prefix .. "d", daily, "today's daily note")
  if opts.telescope then  -- Telescope-пикер вместо vim.ui.select, если есть
    local ok, tel = pcall(require, "telescope.builtin")
    if ok then
      vim.keymap.set("n", prefix .. "t", function()
        vim.ui.input({ prompt = "Second Brain: " }, function(q)
          if not q or q == "" then return end
          api("/search", { query = q, k = 20 }, function(hits)
            tel.quickfix({ title = "second-brain: " .. q, cwd = BRAIN,
              items = vim.tbl_map(function(h)
                return { filename = BRAIN .. "/" .. h.file_path, text = (h.title or "") .. " [" .. (h.heading_path or "") .. "]" }
              end, hits) })
          end)
        end)
      end, { desc = "brain: search → quickfix" })
    end
  end
end
return M
