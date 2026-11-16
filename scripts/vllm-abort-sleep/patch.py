"""Make a vLLM 0.10.x image abort its running requests inside /sleep, like vLLM >= 0.17 does.

Why: before 0.17, /sleep frees the GPU memory even if the engine still holds a request (for
example one whose client went away a moment ago). The engine's next step then uses freed memory
and the container dies ("CUDA error: an illegal memory access"). Wakeful stops running requests
for higher-priority models, so it hits this on purpose. vLLM >= 0.17 needs a newer NVIDIA driver
than some servers have; this patch gives the old image the same behaviour.

What it does (the abort and the sleep call reach the engine in order, so the engine never steps
a request on freed weights):
  1. AsyncLLM.sleep() first aborts every request the API server still tracks;
  2. the version reported by /version gets "+abortsleep" appended, which Wakeful recognises.

Run at image build time, see Dockerfile. Fails loudly if the vLLM source is not what it expects.
"""

import importlib.util
import os
import pathlib
import sys

OLD = """    async def sleep(self, level: int = 1) -> None:
        await self.reset_prefix_cache()
"""
NEW = """    async def sleep(self, level: int = 1) -> None:
        # Wakeful patch, as in vLLM >= 0.17: abort what is still running before the GPU memory
        # is freed. The abort and the sleep call reach the engine in this order.
        running = list(self.output_processor.request_states.keys())
        if running:
            await self.abort(running)
        await self.reset_prefix_cache()
"""
MARKER = "abortsleep"
VERSION_SUFFIX = (
    "\n__version__ = version = __version__ + ('.' if '+' in __version__ else '+') + 'abortsleep'\n"
)


def package_dir() -> pathlib.Path:
    override = os.environ.get("VLLM_DIR")
    if override:
        return pathlib.Path(override)
    spec = importlib.util.find_spec("vllm")  # finds the package without importing it
    if spec is None or not spec.submodule_search_locations:
        sys.exit("vllm is not installed here")
    return pathlib.Path(next(iter(spec.submodule_search_locations)))


def main() -> None:
    root = package_dir()
    engine = root / "v1" / "engine" / "async_llm.py"
    source = engine.read_text()
    if "Wakeful patch" not in source:
        if OLD not in source:
            sys.exit(f"{engine}: AsyncLLM.sleep is not the 0.10.x one this patch is written for")
        engine.write_text(source.replace(OLD, NEW, 1))

    version_file = root / "_version.py"
    text = version_file.read_text()
    if MARKER not in text:
        if "__version__" not in text:
            sys.exit(f"{version_file}: no __version__ to extend")
        version_file.write_text(text + VERSION_SUFFIX)
    namespace: dict[str, object] = {}
    exec(compile(version_file.read_text(), str(version_file), "exec"), namespace)  # noqa: S102
    version = str(namespace["__version__"])
    if MARKER not in version:
        sys.exit(f"{version_file}: the version marker did not take: {version}")
    print(f"patched {engine}; vLLM now reports version {version}")


if __name__ == "__main__":
    main()
