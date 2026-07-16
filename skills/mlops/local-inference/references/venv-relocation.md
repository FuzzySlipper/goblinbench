# Moving a Python venv After Creation

## What Breaks

When you move a venv directory (e.g. `mv .venv /new/location/.venv`), two things break:

1. **Shebangs** — every script in `bin/` has `#!/old/path/bin/python3` hardcoded
2. **pyvenv.cfg** — the `home =` line points to the original Python install location

**What survives**: Python symlinks (`python`, `python3`) in uv-created venvs point to the actual CPython binary (e.g. `~/.local/share/uv/python/cpython-3.12-.../bin/python3.12`), not into the venv itself. These resolve correctly regardless of where the venv lives.

## Diagnosis

```bash
# Check for broken shebangs:
head -1 /new/path/.venv/bin/vllm
# Shows: #!/old/path/.venv/bin/python3  ← broken

# Check pyvenv.cfg:
cat /new/path/.venv/pyvenv.cfg
# home = /old/path/.venv/bin  ← wrong

# Quick test:
/new/path/.venv/bin/vllm --version
# bash: /new/path/.venv/bin/vllm: /old/path/.venv/bin/python3: bad interpreter
```

## Fix Recipe

### Step 1: Fix all shebangs (batch)

```bash
VENV_DIR=/new/path/.venv
OLD_PREFIX=/old/path
NEW_PREFIX=/new/path

# Find all scripts with the old shebang and replace
cd "$VENV_DIR/bin"
grep -rl "#!$OLD_PREFIX/bin/python" . | xargs sed -i "s|#!$OLD_PREFIX/bin/python|#!$NEW_PREFIX/bin/python|g"
```

### Step 2: Fix pyvenv.cfg

```bash
# Update the home entry
sed -i "s|home = .*|home = $NEW_PREFIX/.venv/bin|" "$VENV_DIR/pyvenv.cfg"
```

### Step 3: Verify

```bash
# Shebang should show new path:
head -1 "$VENV_DIR/bin/vllm"

# pyvenv.cfg should show new path:
grep "^home" "$VENV_DIR/pyvenv.cfg"

# Actual test:
"$VENV_DIR/bin/python" -c "import vllm; print(vllm.__version__)"
```

## Example Session

```bash
# Moved venv from /home/patch/.venv to /home/llm/vllm-env/.venv
cd /home/llm/vllm-env/.venv/bin
grep -rl "#!/home/patch/.venv/bin/python" . | xargs sed -i "s|#!/home/patch/.venv/bin/python|#!/home/llm/vllm-env/.venv/bin/python|g"
sed -i "s|home = .*|home = /home/llm/vllm-env/.venv/bin|" /home/llm/vllm-env/.venv/pyvenv.cfg
```

## Alternative: Recreate Instead of Move

If the venv is small or the install is quick, recreating is cleaner:

```bash
cd /new/location
uv venv --python 3.12 vllm-env --seed
source vllm-env/bin/activate
uv pip install vllm --extra-index-url https://wheels.vllm.ai/rocm/
```

This avoids any path issues but requires re-downloading/reinstalling packages.

## Gotchas

- Binary scripts (compiled ELF, like `python` itself) won't have shebangs — only text scripts break
- Symlinks in `bin/` (like `python3 -> python`) are fine — they're relative or point to the real CPython
- Some packages install C extensions with hardcoded paths in `.so` files — rare but possible. Test imports after fixing shebangs.
- If the venv was created with `--seed`, the seed packages (pip, setuptools) may also have hardcoded paths
