import { useState } from "react";

import { api } from "../../api/client";
import type { ManagedModel, ModelCheck, Server } from "../../api/types";
import { FormSection, PresetNumber, Switch } from "../../components/Controls";
import { Icon } from "../../components/Icon";
import { ModalHeader } from "../../components/Modal";
import { Alert, Field, Pill } from "../../components/ui";
import {
  TOOL_PARSERS,
  buildVllmCommand,
  buildVllmLines,
  generateApiKey,
  imageRef,
  servedNameFor,
} from "../../lib/vllmCommand";
import { Link } from "../../router/Link";
import { serverLabel } from "../servers/label";
import { useToast } from "../toast/context";
import { CommandPanel } from "./CommandPanel";
import { CONTEXTS, DEFAULTS, EXAMPLES, IDLES, LAST_STEP, PRIORITIES, STEP_NAMES, nameOf, paramsOf, problemsOf, suggestParser, urlOf, type Form } from "./form";
import { GpuPicker } from "./GpuPicker";

const SUBTITLES = [
  "Which model, and which GPUs does it use?",
  "Keys for the container and for downloading the model.",
  "How much context, and how many requests at once.",
  "How Wakeful treats this model when it is busy or idle.",
  "Rarely needed. The defaults are usually right.",
  "Start the container, then register it.",
] as const;

interface Props {
  registered: ManagedModel[];
  servers: Server[];
  onClose: () => void;
  onRegistered: () => void;
}

/** A step-by-step popup: each step is short enough to see without scrolling. */
export function AddModelDialog({ registered, servers, onClose, onRegistered }: Props) {
  const toast = useToast();
  const [step, setStep] = useState(0);
  const [form, setForm] = useState<Form>({ ...DEFAULTS, server: servers[0]?.name ?? "" });
  const [revealed, setRevealed] = useState(false);
  const [check, setCheck] = useState<ModelCheck>();
  const [busy, setBusy] = useState<"check" | "register" | "create">();

  /** Move to another step. The command always starts with its keys hidden. */
  const goTo = (next: number) => {
    if (next === LAST_STEP) setRevealed(false);
    setStep(next);
  };
  const set = (patch: Partial<Form>) => { setForm((f) => ({ ...f, ...patch })); setCheck(undefined); };
  const pickModel = (model: string) => {
    const parser = suggestParser(model);
    set({ model, ...(parser && !form.parserEdited ? { toolParser: parser } : {}) });
  };

  const name = nameOf(form);
  const url = urlOf(form);
  const params = paramsOf(form);
  const perStep = problemsOf(form, registered);
  const here = step === LAST_STEP ? perStep.flat() : (perStep[step] ?? []);
  const allClear = perStep.every((p) => p.length === 0);
  const chosen = servers.find((s) => s.name === form.server);
  const sharing = registered.filter((m) => m.server === form.server && m.gpus.some((g) => form.gpus.includes(g)));
  const pickServer = (server: string) => {
    const count = servers.find((s) => s.name === server)?.gpu_count ?? 0;
    const kept = form.gpus.filter((g) => g < count);
    set({ server, gpus: kept.length > 0 ? kept : [0] });
  };
  const command = buildVllmCommand(params);
  const servedName = servedNameFor(form.model, form.extraArgs);

  async function runCheck() {
    setBusy("check");
    try {
      setCheck(await api.checkModel({ url, server: form.server, served_name: servedName, backend_api_key: form.apiKey || null }));
    } catch (err) {
      toast.show("error", err instanceof Error ? err.message : "The check failed.");
    }
    setBusy(undefined);
  }

  /** Have the server's agent create the container, and register it as a model in one go. */
  async function createAndRegister() {
    setBusy("create");
    try {
      await api.createContainer(form.server, {
        name,
        model: form.model,
        image: imageRef(form.imageTag),
        port: Number(form.port),
        gpus: form.gpus,
        cache_dir: form.cacheDir,
        api_key: form.apiKey || null,
        hf_token: form.hfToken || null,
        max_model_len: Number(form.maxModelLen),
        max_num_seqs: Number(form.maxNumSeqs),
        memory_share: Number(form.memoryShare),
        allow_long_context: form.allowLongContext,
        tool_calling: form.toolCalling,
        tool_parser: form.toolParser,
        auto_restart: form.autoRestart,
        extra_args: form.extraArgs.trim().replace(/\s+/g, " "),
        register_as: { name, url, served_name: servedName, idle_minutes: Number(form.idle), priority: Number(form.priority) },
      });
      toast.show("success", `“${name}” is starting on ${form.server}. It loads for a few minutes, then Wakeful puts it to sleep until a request arrives.`);
      onRegistered();
    } catch (err) {
      toast.show("error", err instanceof Error ? err.message : "Could not create the container.");
      setBusy(undefined);
    }
  }

  async function register() {
    setBusy("register");
    try {
      await api.registerModel({
        name,
        server: form.server,
        url,
        served_name: servedName,
        gpus: form.gpus,
        idle_minutes: Number(form.idle),
        priority: Number(form.priority),
        backend_api_key: form.apiKey || null,
      });
      toast.show("success", `“${name}” registered. It wakes when a request arrives.`);
      onRegistered();
    } catch (err) {
      toast.show("error", err instanceof Error ? err.message : "Could not register the model.");
      setBusy(undefined);
    }
  }

  return (
    <>
      <ModalHeader title="Add a model" subtitle={SUBTITLES[step]} onClose={onClose} />
      <ol className="stepper" aria-label="Progress">
        {STEP_NAMES.map((label, i) => (
          <li key={label} className={i < step ? "done" : ""} aria-current={i === step ? "step" : undefined}>
            {i < step ? (
              <button type="button" className="step-btn" onClick={() => { goTo(i); }} aria-label={`Back to ${label}`}>
                <span className="dot"><Icon name="check" size={13} /></span><span className="step-label">{label}</span>
              </button>
            ) : (
              <span className="step-btn"><span className="dot">{i + 1}</span><span className="step-label">{label}</span></span>
            )}
          </li>
        ))}
      </ol>

      <div className={`modal-body ${step === LAST_STEP ? "fit" : ""}`}>
        {step === 0 ? (
          <>
            <Field label="Hugging Face model">
              <input className="input" type="text" placeholder="openai/gpt-oss-20b" spellCheck={false} autoCapitalize="none" autoComplete="off" autoFocus value={form.model} onChange={(e) => { pickModel(e.target.value.trim()); }} />
            </Field>
            <div className="presets" aria-label="Examples">
              {EXAMPLES.map((example) => (
                <button key={example} type="button" className="chip-btn" onClick={() => { pickModel(example); }}>{example}</button>
              ))}
            </div>
            {servers.length === 0 ? (
              <div className="callout">
                <strong>Register a server first.</strong> Models are placed on a server so GPU numbers are unambiguous. Add one on the <Link to="/servers">Servers</Link> page, then come back.
              </div>
            ) : (
              <Field label="Server it runs on">
                <select className="input" value={form.server} onChange={(e) => { pickServer(e.target.value); }}>
                  {servers.map((s) => <option key={s.name} value={s.name}>{serverLabel(s)}</option>)}
                </select>
              </Field>
            )}
            <div className="field-row">
              <Field label="Name clients use">
                <input className="input" type="text" maxLength={64} spellCheck={false} autoCapitalize="none" value={name} onChange={(e) => { set({ name: e.target.value, nameEdited: true }); }} />
              </Field>
              <Field label="Port on that server">
                <input className="input" type="number" min={1024} max={65535} inputMode="numeric" value={form.port} onChange={(e) => { set({ port: e.target.value }); }} />
              </Field>
            </div>
            <div className="field">
              <span>GPUs it fills while awake</span>
              <GpuPicker count={chosen?.gpu_count ?? 0} value={form.gpus} onChange={(gpus) => { set({ gpus }); }} />
            </div>
            {form.gpus.length > 1 ? <p className="hint dim">The model is split across {form.gpus.length} GPUs; the command includes it.</p> : null}
            {chosen?.tunnel ? (
              <p className="hint dim">{chosen.name} connects out to Wakeful, so the container&rsquo;s address is the one on that machine (<code>http://127.0.0.1:{form.port}</code>). Wakeful reaches it through the agent.</p>
            ) : servers.length > 1 ? (
              <p className="hint dim">Wakeful reaches the container at the address on the Advanced step. It starts as this machine; for another server, enter that server's address there.</p>
            ) : null}
            {sharing.length > 0 ? (
              <div className="callout">
                <strong>Shared GPU.</strong> {sharing.map((m) => m.name).join(", ")} already {sharing.length === 1 ? "uses" : "use"} {form.gpus.length === 1 ? "this GPU" : "one of these GPUs"} on {form.server}. That works: Wakeful loads one at a time and swaps them. Set a priority on the Sleep step to say which goes first.
              </div>
            ) : null}
          </>
        ) : null}

        {step === 1 ? (
          <>
            <FormSection title="Container API key" hint="Optional. If set, the container requires this key. Wakeful stores it so it can call the container, and the same key goes into the command.">
              <div className="input-group">
                <input className="input" type={revealed ? "text" : "password"} autoComplete="off" spellCheck={false} placeholder="sk-…" aria-label="Container API key" value={form.apiKey} onChange={(e) => { set({ apiKey: e.target.value.trim() }); }} />
                <button type="button" className="btn small" onClick={() => { set({ apiKey: generateApiKey() }); setRevealed(true); }}>Generate</button>
              </div>
            </FormSection>
            <FormSection title="Hugging Face token" hint="Optional, only for gated models. It goes into the command and is never sent to Wakeful.">
              <input className="input" type={revealed ? "text" : "password"} autoComplete="off" spellCheck={false} placeholder="hf_…" aria-label="Hugging Face token" value={form.hfToken} onChange={(e) => { set({ hfToken: e.target.value.trim() }); }} />
            </FormSection>
            <button type="button" className="btn small link-btn" onClick={() => { setRevealed(!revealed); }}>
              <Icon name={revealed ? "eye-off" : "eye"} size={15} /> {revealed ? "Hide keys" : "Show keys"}
            </button>
          </>
        ) : null}

        {step === 2 ? (
          <>
            <FormSection title="Capacity">
              <PresetNumber label="Context length (tokens)" options={CONTEXTS} value={form.maxModelLen} onChange={(v) => { set({ maxModelLen: v }); }} min={256} />
              <div className="field-row">
                <Field label="Requests at once">
                  <input className="input" type="number" min={1} inputMode="numeric" value={form.maxNumSeqs} onChange={(e) => { set({ maxNumSeqs: e.target.value }); }} />
                </Field>
                <Field label={`GPU memory share · ${Math.round(Number(form.memoryShare) * 100)}%`}>
                  <input className="range" type="range" min={0.5} max={0.98} step={0.01} value={form.memoryShare} onChange={(e) => { set({ memoryShare: e.target.value }); }} aria-label="GPU memory share" />
                </Field>
              </div>
            </FormSection>
            <FormSection title="Features">
              <Switch checked={form.allowLongContext} onChange={(on) => { set({ allowLongContext: on }); }} label="Allow a longer context than the model’s default" hint="Adds VLLM_ALLOW_LONG_MAX_MODEL_LEN=1." />
              <Switch checked={form.toolCalling} onChange={(on) => { set({ toolCalling: on }); }} label="Tool calling" hint="Lets clients use function calls. Pick the parser that matches the model." />
              {form.toolCalling ? (
                <Field label="Tool-call parser">
                  <input className="input" list="parsers" spellCheck={false} value={form.toolParser} onChange={(e) => { set({ toolParser: e.target.value.trim(), parserEdited: true }); }} />
                  <datalist id="parsers">{TOOL_PARSERS.map((p) => <option key={p} value={p} />)}</datalist>
                </Field>
              ) : null}
            </FormSection>
          </>
        ) : null}

        {step === 3 ? (
          <>
            <FormSection title="Priority" hint="When two models share a GPU and both have requests waiting, the higher number goes first: the other one finishes what it is running, then steps aside.">
              <PresetNumber label="Priority" options={PRIORITIES} value={form.priority} onChange={(v) => { set({ priority: v }); }} min={0} max={100} />
            </FormSection>
            <FormSection title="Sleep after idle" hint="How long the model waits with no requests before it gives its GPU memory back. This applies whatever the priority.">
              <PresetNumber label="Minutes" options={IDLES} value={form.idle} onChange={(v) => { set({ idle: v }); }} min={0.1} step="any" />
            </FormSection>
          </>
        ) : null}

        {step === 4 ? (
          <>
            <div className="field-row">
              <Field label="vLLM image">
                <input className="input" type="text" spellCheck={false} value={form.imageTag} onChange={(e) => { set({ imageTag: e.target.value.trim() }); }} />
              </Field>
              <Field label="Model cache folder">
                <input className="input" type="text" spellCheck={false} value={form.cacheDir} onChange={(e) => { set({ cacheDir: e.target.value.trim() }); }} />
              </Field>
            </div>
            <Field label="Extra vLLM arguments">
              <input className="input" type="text" spellCheck={false} placeholder="--dtype bfloat16 --served-model-name my-model" value={form.extraArgs} onChange={(e) => { set({ extraArgs: e.target.value }); }} />
            </Field>
            <Field label="Container address (if it is not on this machine)">
              <input className="input" type="text" spellCheck={false} value={url} onChange={(e) => { set({ url: e.target.value.trim(), urlEdited: true }); }} />
            </Field>
            <Switch checked={form.autoRestart} onChange={(on) => { set({ autoRestart: on }); }} label="Restart automatically" hint="Adds --restart unless-stopped, so the container comes back after a reboot." />
            {form.autoRestart && sharing.length > 0 ? (
              <div className="callout warn">After a reboot, containers that share a GPU all start awake at once and can run out of memory. Turn this off for models that share a GPU, and start them one at a time with <code className="mono">scripts/bootstrap.sh</code>.</div>
            ) : null}
          </>
        ) : null}

        {step === LAST_STEP ? (
          <>
            {chosen?.has_agent ? (
              <div className="callout start-choice">
                <strong>{chosen.name} has an agent.</strong>
                <span>Wakeful can start this container for you and register it in one step, with the settings above. The Hugging Face token, if you entered one, is sent to the agent once and not stored by Wakeful.</span>
                <span className="dim">Or run the command yourself below and register it afterwards.</span>
              </div>
            ) : null}
            <FormSection grow title="1 · Start the container" hint="Run this on the GPU machine. Highlighted lines are what Wakeful needs for sleep mode.">
              <CommandPanel lines={buildVllmLines(params, revealed)} command={command} hasSecrets={form.apiKey !== "" || form.hfToken !== ""} revealed={revealed} onReveal={setRevealed} />
            </FormSection>
            <FormSection title="2 · Register it" hint="Once it is running, test the connection, then register. A container that is awake is put to sleep.">
              {check ? <CheckResult result={check} hasKey={form.apiKey !== ""} /> : <p className="hint dim">Nothing tested yet.</p>}
            </FormSection>
          </>
        ) : null}
      </div>

      <footer className="modal-foot">
        {here.length === 0 ? <span className="spacer" /> : form.model === "" ? <span className="foot-hint">{here[0]}</span> : <Alert notice={{ kind: "error", text: here[0] ?? "" }} />}
        {step === 0 ? <button type="button" className="btn" onClick={onClose}>Cancel</button> : <button type="button" className="btn" onClick={() => { goTo(step - 1); }}><Icon name="arrow-left" size={16} /> Back</button>}
        {step > 0 && step < LAST_STEP && allClear ? <button type="button" className="btn link-btn" onClick={() => { goTo(LAST_STEP); }}>Skip to command</button> : null}
        {step < LAST_STEP ? (
          <button type="button" className="btn primary" disabled={here.length > 0} onClick={() => { goTo(step + 1); }}>Next <Icon name="arrow-right" size={16} /></button>
        ) : (
          <>
            <button type="button" className="btn" disabled={busy !== undefined || here.length > 0} onClick={() => void runCheck()}>{busy === "check" ? "Testing…" : "Test connection"}</button>
            <button type="button" className={`btn ${chosen?.has_agent ? "" : "primary"}`} disabled={busy !== undefined || here.length > 0} onClick={() => void register()}>{busy === "register" ? "Registering…" : "Register model"}</button>
            {chosen?.has_agent ? (
              <button type="button" className="btn primary" disabled={busy !== undefined || here.length > 0} onClick={() => void createAndRegister()}>{busy === "create" ? "Creating (may download the image)…" : "Create and register"}</button>
            ) : null}
          </>
        )}
      </footer>
    </>
  );
}

function CheckResult({ result, hasKey }: { result: ModelCheck; hasKey: boolean }) {
  const rows: [string, boolean | null, string][] = [
    ["Reachable", result.reachable, ""],
    ["Sleep endpoints", result.reachable ? result.sleep_endpoints : null, result.state ?? ""],
    ["Model found", result.served_name_found, result.served_models.join(", ")],
    ["API key accepted", hasKey ? result.key_accepted : null, ""],
  ];
  return (
    <div className="check" role="status">
      <div className="check-items">
        {rows.map(([label, ok, detail]) => (
          <span key={label} className="check-item">
            {ok === null ? <Pill tone="idle">n/a</Pill> : ok ? <Pill tone="ok">ok</Pill> : <Pill tone="bad">no</Pill>}
            <span>{label}</span>
            {detail ? <span className="dim mono">{detail}</span> : null}
          </span>
        ))}
      </div>
      {result.problems.length > 0 ? <ul className="problems">{result.problems.map((p) => <li key={p}>{p}</li>)}</ul> : <p className="check-ok">Everything looks right. You can register it.</p>}
    </div>
  );
}
