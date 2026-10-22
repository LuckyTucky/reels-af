"""reel-af — turn a URL or a topic into a vertical viral reel.

Two entry reasoners; everything else is a supporting reasoner in the
control-plane DAG so the workflow is fully introspectable.

    article_to_reel(url)   ─┐
                            │   shared downstream:
    topic_to_reel(topic)   ─┤   synthesize_audio → pack_cards → plan_beats
                                → plan_visuals ∥ plan_accents
                                → generate_videos → stitch_reel
                                → final mp4

Article path:
    URL → extract_essence → compose_script → (audio, beats, visuals,
    accents, videos) → stitch_reel

Topic path (multi-reasoner hunter cascade):
    topic → 4 parallel hunters (specific_figure, reversal, temporal,
            cross_domain) producing 12 candidates → critic picks top 3
            → 3 parallel narrators write delayed-reveal scripts →
            pairwise judge picks the winner → the same downstream
            audio/beats/visuals/accents/videos/stitch path.

Run the agent (registers with the AgentField control plane, serves
reasoners on :8002):

    af server                                  # control plane
    cd examples/reel-af && uv run python -m reel_af.app

Invoke async, get an execution_id immediately:

    curl -X POST http://localhost:8080/api/v1/execute/async/reel-af.reel_article_to_reel \\
        -H 'Content-Type: application/json' \\
        -d '{"input":{"url":"https://example.com/article"}}'

    curl -X POST http://localhost:8080/api/v1/execute/async/reel-af.reel_topic_to_reel \\
        -H 'Content-Type: application/json' \\
        -d '{"input":{"topic":"philosophy of mind"}}'
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_PROJECT_ROOT / ".env")

from agentfield import Agent, AgentRouter, AIConfig  # noqa: E402

# Apply SDK bug-fixes at startup so every OpenRouterProvider call gets
# the fixed behaviour. Module is idempotent.
import reel_af.sdk_patches  # noqa: E402, F401
from reel_af.render import cost as cost_track  # noqa: E402

app = Agent(
    node_id=os.getenv("AGENT_NODE_ID", "reel-af"),
    agentfield_server=os.getenv("AGENTFIELD_SERVER", "http://localhost:8080"),
    version="1.0.0",
    description="URL or topic → vertical viral reel via a multi-reasoner DAG.",
    ai_config=AIConfig(
        model=os.getenv("REEL_AF_MODEL", "openrouter/deepseek/deepseek-v4-pro"),
        # Reasoning endpoint defaults to OpenRouter. Advanced users can point
        # `.ai()` calls at any OpenAI-compatible endpoint (local vLLM/Ollama,
        # a self-hosted gateway, another aggregator) without code changes:
        #   REEL_AF_API_KEY  overrides the key (falls back to OPENROUTER_API_KEY)
        #   REEL_AF_API_BASE overrides the base URL (empty/unset → OpenRouter)
        # Media (TTS/image/video) still routes through OpenRouter, so
        # OPENROUTER_API_KEY remains required. See README "Bring your own model".
        api_key=os.getenv("REEL_AF_API_KEY") or os.environ.get("OPENROUTER_API_KEY", ""),
        api_base=os.getenv("REEL_AF_API_BASE") or "https://openrouter.ai/api/v1",
    ),
    dev_mode=True,
)

# All reel reasoners live under prefix "reel".
reel = AgentRouter(prefix="reel", tags=["video", "viral"])


# ════════════════════════════════════════════════════════════════════
# Article-only reasoners — URL → Essence → ScriptDraft
# ════════════════════════════════════════════════════════════════════


@reel.reasoner()
async def extract_essence(url: str) -> dict:
    """Phase 1 — URL → Essence (one harness call).

    Fetches the article, distills the most surprising claim + mechanism
    + evidence + content_mode + domain in one structured pass.
    """
    from reel_af.agents.extract import extract_essence as _extract

    essence = await _extract(app, url)
    return {"essence": essence.model_dump()}


@reel.reasoner()
async def pick_hook(essence: dict, lang: str = "") -> dict:
    """Phase 1.5 — Essence → meilleure accroche parmi 2-3 (mode article).

    Génère 2-3 candidats en UN appel .ai(), chacun auto-noté sur
    hookability/spécificité (vocabulaire repris de critic.py). Choisit
    mécaniquement le mieux noté — pas de 2e appel juge. Comble l'écart
    avec le mode sujet (hunters/critic/judge), dont ce reasoner s'inspire
    sans dupliquer toute la cascade — une seule essence, pas de recherche
    d'angle, juste de formulation.

    `lang` ("fr"/"en") — vide = repli sur REEL_AF_LANG.
    """
    from reel_af.agents.hook import pick_hook as _pick_hook
    from reel_af.models import Essence

    e = Essence(**essence)
    pick = await _pick_hook(app, e, lang=lang)
    return {"hook_pick": pick.model_dump()}


@reel.reasoner()
async def compose_script(
    essence: dict, chosen_hook: dict | None = None, lang: str = "",
) -> dict:
    """Phase 2 — Essence → ScriptDraft (one .ai() call).

    Fixed Hook → Mechanism → Payoff structure with inline Gemini TTS
    audio tags. The schema's loop-back validator enforces the final
    clause to echo a keyword from the hook so the reel rewatches.

    If chosen_hook is given (from reel_pick_hook), the hook is FIXED —
    this call only writes mechanism/payoff around it. `lang` ("fr"/"en")
    — vide = repli sur REEL_AF_LANG.
    """
    from reel_af.agents.compose import compose_script as _compose
    from reel_af.models import Essence, HookCandidate

    e = Essence(**essence)
    hook = HookCandidate(**chosen_hook) if chosen_hook else None
    script = await _compose(app, e, chosen_hook=hook, lang=lang)
    return {"script": script.model_dump()}


# ════════════════════════════════════════════════════════════════════
# Topic-only reasoners — 4 hunters + critic + narrator + judge
# ════════════════════════════════════════════════════════════════════


@reel.reasoner()
async def hunt_specific_figure(topic: str) -> dict:
    """Hunter A — 3 candidates centered on a NAMED person most viewers
    haven't heard of. Names the year, names the finding."""
    from reel_af.agents.hunters import hunt_specific_figure as _hunt

    candidates = await _hunt(app, topic)
    return {"candidates": [c.model_dump() for c in candidates]}


@reel.reasoner()
async def hunt_reversal(topic: str) -> dict:
    """Hunter B — 3 candidates where the common interpretation is
    BACKWARDS, with the source of the reversal named."""
    from reel_af.agents.hunters import hunt_reversal as _hunt

    candidates = await _hunt(app, topic)
    return {"candidates": [c.model_dump() for c in candidates]}


@reel.reasoner()
async def hunt_temporal(topic: str) -> dict:
    """Hunter C — 3 candidates tied to a specific year/event that
    reframes how we see the field."""
    from reel_af.agents.hunters import hunt_temporal as _hunt

    candidates = await _hunt(app, topic)
    return {"candidates": [c.model_dump() for c in candidates]}


@reel.reasoner()
async def hunt_cross_domain(topic: str) -> dict:
    """Hunter D — 3 candidates bridging the topic to an unexpected
    other field, with the specific bridge-builder named."""
    from reel_af.agents.hunters import hunt_cross_domain as _hunt

    candidates = await _hunt(app, topic)
    return {"candidates": [c.model_dump() for c in candidates]}


@reel.reasoner()
async def pick_top_essences(
    topic: str, candidates: list[dict], n_top: int = 3,
) -> dict:
    """Critic — scores 12 candidates on novelty / specificity /
    hookability / narratability and picks the top N preferring angle
    diversity when scores are close."""
    from reel_af.agents.critic import pick_top_essences as _crit
    from reel_af.models import EssenceCandidate

    cand_objs = [EssenceCandidate(**c) for c in candidates]
    out = await _crit(app, topic, cand_objs, n=n_top)
    chosen = [i for i in out.chosen_indices if 0 <= i < len(cand_objs)]
    return {
        "rankings": [r.model_dump() for r in out.rankings],
        "chosen_indices": chosen,
        "chosen_essences": [cand_objs[i].model_dump() for i in chosen],
    }


@reel.reasoner()
async def write_narrations(essences: list[dict]) -> dict:
    """Narrator fan-out — one delayed-reveal script per chosen essence
    (parallel via asyncio.gather)."""
    from reel_af.agents.narrator import write_narrations as _narr
    from reel_af.models import EssenceCandidate

    ess_objs = [EssenceCandidate(**e) for e in essences]
    scripts = await _narr(app, ess_objs)
    return {"scripts": [s.model_dump() for s in scripts]}


@reel.reasoner()
async def pick_best_narration(
    topic: str, scripts: list[dict], essences: list[dict],
) -> dict:
    """Pairwise judge — picks the most viral script."""
    from reel_af.agents.judge import pick_best_narration as _judge
    from reel_af.models import ConversationalScript, EssenceCandidate

    script_objs = [ConversationalScript(**s) for s in scripts]
    ess_objs = [EssenceCandidate(**e) for e in essences]
    if len(script_objs) == 1:
        return {"winner_idx": 0, "composite_score": 7.0, "why": "only one"}
    verdict = await _judge(app, topic, script_objs, ess_objs)
    return verdict.model_dump()


# ════════════════════════════════════════════════════════════════════
# Shared downstream — audio, beats, visuals, accents, videos, stitch
# ════════════════════════════════════════════════════════════════════


@reel.reasoner()
async def synthesize_audio(
    narration: str, voice_tone: str, out_dir: str, target_wpm: int = 180,
    lang: str = "", voice_preset: str = "",
) -> dict:
    """Sentence-by-sentence TTS + sample-accurate word timings.

    Each sentence synthesizes independently (in parallel), is sped-up via
    ffmpeg ``atempo`` — ADAPTIVELY per sentence, targeting target_wpm,
    since each sentence's natural Gemini speaking rate varies with no
    shared context between calls (preserves pitch), measured with
    ffprobe, then native-wave concatenated. Sentence boundaries are
    sample-accurate on the final timeline; words within a sentence
    are distributed by syllable count.

    `lang` ("fr"/"en") pick une voix Gemini adaptée — vide = repli sur
    REEL_AF_LANG. `voice_preset` ("voice1".."voice10", text_to_reel
    seulement) prime sur le choix par ton — voir render/tts.VOICE_PRESETS.
    """
    from reel_af.render.tts import (
        resolve_voice_preset,
        strip_tts_tags,
        synthesize_audio as _synth,
    )

    voice = resolve_voice_preset(voice_preset, voice_tone, lang=lang)
    audio_path, word_timings = await _synth(
        narration=narration, voice=voice, out_dir=Path(out_dir),
        target_wpm=target_wpm,
    )
    duration_s = word_timings[-1].end_s if word_timings else 0.0
    return {
        "audio_path": str(audio_path),
        "duration_s": duration_s,
        "voice": voice,
        "word_timings": [w.model_dump() for w in word_timings],
        "spoken_narration": strip_tts_tags(narration),
    }


@reel.reasoner()
async def pack_cards(word_timings: list[dict]) -> dict:
    """WordTimings → Cards for subtitle layout. Pure code, no LLM."""
    from reel_af.models import WordTiming
    from reel_af.planning.cards import pack_cards as _pack

    wts = [WordTiming(**w) for w in word_timings]
    cards = _pack(wts)
    return {"cards": [c.model_dump() for c in cards]}


@reel.reasoner()
async def plan_beats(script: dict, audio_duration_s: float) -> dict:
    """ScriptDraft → Beats. One Beat per (hook | mechanism_line | payoff).

    Each beat gets a fixed Veo bucket (4 / 6 / 8 s) chosen by role
    (hook floors at 6s; payoff caps at 4s for the snappy loop close;
    mechanism uses the smallest bucket ≥ word-share estimate + safety).
    """
    from reel_af.models import ScriptDraft
    from reel_af.planning.beats import plan_beats as _plan

    s = ScriptDraft(**script)
    beats = _plan(s, audio_duration_s)
    if not beats:
        raise RuntimeError("plan_beats: zero beats from non-empty script.")
    return {"beats": [b.model_dump() for b in beats]}


@reel.reasoner()
async def plan_visuals(
    beats: list[dict], essence: dict, spoken_narration: str,
) -> dict:
    """Per-beat first-frame image prompt + motion hint (parallel fan-out)."""
    from reel_af.agents.visual import plan_beat_visuals
    from reel_af.models import Beat, Essence

    beat_objs = [Beat(**b) for b in beats]
    e = Essence(**essence)
    visuals = await plan_beat_visuals(
        app, beat_objs, e, full_narration=spoken_narration,
    )
    return {"visuals": [v.model_dump() for v in visuals]}


@reel.reasoner()
async def plan_accents(beats: list[dict], essence: dict, lang: str = "") -> dict:
    """Per-beat optional editorial overlay (parallel fan-out, biased to None).

    Six canonical patterns: number, named_entity, jargon_translation,
    hook_title_card, reaction, list_marker. Most beats return None.

    `lang` ("fr"/"en") — vide = repli sur REEL_AF_LANG.
    """
    from reel_af.agents.accent import plan_beat_accents
    from reel_af.models import Beat, Essence

    beat_objs = [Beat(**b) for b in beats]
    e = Essence(**essence)
    accents = await plan_beat_accents(app, beat_objs, e, lang=lang)
    return {
        "accents": [a.model_dump() if a is not None else None for a in accents],
    }


@reel.reasoner()
async def generate_videos(
    beats: list[dict],
    visuals: list[dict],
    content_mode: str,
    out_dir: str,
    art_style: str = "",
    person_photo: str = "",
) -> dict:
    """Per-beat first-frame + Veo i2v (parallel fan-out).

    Two-tier fallback per beat: image fail → placeholder + ken-burns;
    Veo fail → real first-frame + ken-burns. A single beat failure
    never crashes the whole reel.

    ``art_style`` names a preset from ``render.images._ART_STYLE_PRESETS``
    (e.g. "style1") to override the default content_mode-based visual style
    for this reel only — no restart needed to A/B test different looks.
    ``person_photo`` (optionnel, text_to_reel seulement) : id d'une photo
    de la personne-sujet (bon-stock/person-refs/<id>.jpg) jointe en entrée
    de CHAQUE beat — voir render/images.generate_first_frame.
    """
    from reel_af.models import Beat, BeatVisual
    from reel_af.render.video import generate_beat_videos

    beat_objs = [Beat(**b) for b in beats]
    visual_objs = [BeatVisual(**v) for v in visuals]
    media_dir = Path(out_dir) / "media"
    artifacts = await generate_beat_videos(
        beats=beat_objs,
        visuals=visual_objs,
        out_dir=media_dir,
        content_mode=content_mode,
        art_style=art_style,
        person_photo=person_photo,
    )
    return {"artifacts": [a.model_dump(mode="json") for a in artifacts]}


@reel.reasoner()
async def stitch_reel(
    beats: list[dict],
    artifacts: list[dict],
    cards: list[dict],
    accents: list[dict | None],
    audio_path: str,
    out_dir: str,
    run_id: str,
) -> dict:
    """Single-pass ffmpeg: concat filter + libass + AAC mux."""
    from reel_af.models import AccentOverlay, Beat, BeatArtifact, Card
    from reel_af.render.stitch import stitch_reel as _stitch

    beat_objs = [Beat(**b) for b in beats]
    artifact_objs = [BeatArtifact(**a) for a in artifacts]
    card_objs = [Card(**c) for c in cards]
    accent_objs = [
        AccentOverlay(**a) if a is not None else None for a in accents
    ]
    final = await _stitch(
        beats=beat_objs,
        artifacts=artifact_objs,
        cards=card_objs,
        accents=accent_objs,
        full_audio_path=Path(audio_path),
        out_dir=Path(out_dir),
        run_id=run_id,
    )
    return {"video_path": str(final)}


# ════════════════════════════════════════════════════════════════════
# STABILITÉ — un seul reel rendu à la fois (verrou global du moteur)
# ════════════════════════════════════════════════════════════════════
# Peu importe COMMENT un reel est lancé (reel.sh, bouton 🎬, script, ou
# plusieurs commandes d'un coup), le moteur n'en traite qu'UN à la fois : les
# autres attendent leur tour ici. Fini les rendus parallèles qui se ralentissent
# mutuellement et saturent le modèle. C'est la garantie de stabilité, au niveau
# du moteur plutôt que de la méthode de lancement.
_REEL_RENDER_LOCK = asyncio.Semaphore(1)


# ════════════════════════════════════════════════════════════════════
# ENTRY REASONER 1 — Article → Reel
# ════════════════════════════════════════════════════════════════════


@reel.reasoner()
async def article_to_reel(
    url: str, out_dir: str | None = None, art_style: str = "", lang: str = "",
) -> dict:
    """Turn an article URL into a vertical viral reel.

    Composes the DAG via ``app.call`` so every phase is a visible node
    in the control plane and individually re-runnable.

    Un seul reel se rend à la fois (verrou global _REEL_RENDER_LOCK) :
    les lancements simultanés sont sérialisés par le moteur.

    ``art_style`` : nom d'un preset visuel (ex. "style1") pour A/B tester
    un style d'image sans redémarrer — voir render/images.py.
    ``lang`` : "fr" ou "en" ; vide = repli sur REEL_AF_LANG. Paramètre PAR
    REEL, comme art_style — pas besoin de redémarrer pour changer.

    Example:
      curl -X POST http://localhost:8080/api/v1/execute/async/reel-af.reel_article_to_reel \\
        -H 'Content-Type: application/json' \\
        -d '{"input":{"url":"https://example.com/article","art_style":"style1","lang":"fr"}}'
    """
    if "OPENROUTER_API_KEY" not in os.environ:
        return {"error": "OPENROUTER_API_KEY not set in env."}
    async with _REEL_RENDER_LOCK:
        return await _article_to_reel_locked(url, out_dir, art_style, lang)


async def _article_to_reel_locked(
    url: str, out_dir: str | None = None, art_style: str = "", lang: str = "",
) -> dict:
    run_id = uuid.uuid4().hex[:8]
    out_path = (
        Path(out_dir) if out_dir else (Path.cwd() / "output" / f"article-{run_id}")
    )
    out_path.mkdir(parents=True, exist_ok=True)
    media_dir = out_path / "media"
    media_dir.mkdir(parents=True, exist_ok=True)

    # Un seul reel rendu à la fois (_REEL_RENDER_LOCK) → un accumulateur
    # global suffit pour capter le coût réel de CE run.
    app.cost_tracker.reset()
    cost_track.reset()

    timings: dict[str, float] = {}
    node = app.node_id
    app.note(
        f"reel-af article: starting run {run_id} for {url}",
        tags=["reel", "article", "start"],
    )
    t_pipeline = time.time()

    # Phase 1 — extract
    t = time.time()
    try:
        e_out = await app.call(f"{node}.reel_extract_essence", url=url)
    except Exception as exc:  # noqa: BLE001
        # Échec visible : au lieu d'un dossier vide, on écrit pourquoi.
        (out_path / "ERREUR.txt").write_text(
            "Reel NON produit.\n"
            f"URL      : {url}\n"
            "Étape    : extraction de l'article\n"
            f"Raison   : {exc}\n",
            encoding="utf-8",
        )
        app.note(
            f"reel-af article: run {run_id} FAILED at extract — {exc}",
            tags=["reel", "article", "error"],
        )
        return {
            "error": str(exc),
            "stage": "extract",
            "url": url,
            "run_id": run_id,
            "erreur_fichier": str(out_path / "ERREUR.txt"),
        }
    timings["extract"] = round(time.time() - t, 1)
    essence = e_out["essence"]

    # Phase 1.5 — meilleure accroche parmi 2-3 candidats
    t = time.time()
    h_out = await app.call(f"{node}.reel_pick_hook", essence=essence, lang=lang)
    timings["hook"] = round(time.time() - t, 1)
    chosen_hook = h_out["hook_pick"]["chosen"]

    # Phase 2 — compose (hook déjà fixé)
    t = time.time()
    c_out = await app.call(
        f"{node}.reel_compose_script", essence=essence, chosen_hook=chosen_hook,
        lang=lang,
    )
    timings["compose"] = round(time.time() - t, 1)
    script = c_out["script"]

    final = await _render_downstream(
        node=node,
        essence=essence,
        script=script,
        out_path=out_path,
        media_dir=media_dir,
        run_id=run_id,
        timings=timings,
        art_style=art_style,
        lang=lang,
    )

    cost_report = cost_track.write(out_path, app.execution_cost)

    timings["total"] = round(time.time() - t_pipeline, 1)
    app.note(
        f"reel-af article: run {run_id} done → {final['video_path']}",
        tags=["reel", "article", "done"],
    )
    return {
        **final,
        "source": "article",
        "url": url,
        "hook": script["hook"],
        "hook_variant": script["hook_variant"],
        "hookability_score": chosen_hook["hookability"],
        "content_mode": essence["content_mode"],
        "domain": essence["domain"],
        "run_id": run_id,
        "timings_s": timings,
        "cost_usd": cost_report["total_cost_usd"],
    }


def _script_from_verbatim_text(text: str) -> dict:
    """text_to_reel mode='verbatim' : découpe pure (aucune réécriture) du
    texte collé en un dict compatible ScriptDraft — hook = 1re phrase,
    payoff_line = dernière phrase, mechanism_lines = phrases du milieu
    regroupées en 2-4 blocs. `narration` reste le texte tel quel (espaces
    normalisés), donc le TTS lit exactement les mots de Luc.
    `skip_loop_check=True` car un texte collé n'a aucune raison de boucler
    naturellement sur son ouverture (contrainte réservée au mode brute)."""
    narration = " ".join(text.strip().split())
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", narration) if s.strip()]
    if not sentences:
        sentences = [narration or "."]

    hook = sentences[0]
    payoff_line = sentences[-1] if len(sentences) > 1 else sentences[0]
    middle = sentences[1:-1] if len(sentences) > 2 else []

    if len(middle) > 4:
        buckets: list[list[str]] = [[] for _ in range(4)]
        for i, s in enumerate(middle):
            buckets[i * 4 // len(middle)].append(s)
        middle = [" ".join(b) for b in buckets if b]
    while len(middle) < 2:
        # ScriptDraft impose min_length=2 sur mechanism_lines — un texte
        # trop court (1-2 phrases) réutilise hook/payoff plutôt que
        # d'inventer du texte.
        filler = payoff_line if hook not in middle else hook
        middle.append(filler)

    return {
        "hook": hook,
        "hook_variant": "curiosity_gap",
        "mechanism_lines": middle[:4],
        "payoff_line": payoff_line,
        "target_wpm": 165,
        "narration": narration,
        "skip_loop_check": True,
    }


# ════════════════════════════════════════════════════════════════════
# ENTRY REASONER 3 — Texte collé → Reel
# ════════════════════════════════════════════════════════════════════


@reel.reasoner()
async def text_to_reel(
    text: str,
    out_dir: str | None = None,
    art_style: str = "",
    mode: str = "brute",
    lang: str = "",
    voice_preset: str = "",
    person_photo: str = "",
) -> dict:
    """Turn pasted text into a vertical viral reel (no URL).

    ``mode == "brute"`` (défaut) : le texte remplace l'« essence » — on
    saute l'extraction (pas d'URL/fetch), puis hook.py + compose.py
    tournent normalement dessus (même pipeline que article_to_reel, privé
    de l'étape extract).

    ``mode == "verbatim"`` : on saute hook.py ET compose.py. Le texte
    devient directement la narration, telle quelle (aucune réécriture) —
    seulement découpé en phrases pour les timings/beats.

    ``voice_preset`` : "voice1".."voice10" (voir render/tts.VOICE_PRESETS) ;
    vide = repli sur le choix par ton habituel. voice1 = voix actuellement
    en prod.

    ``person_photo`` : id d'une photo de la personne-sujet du reel (voir
    POST /api/reel-af/person-photo), jointe en entrée de CHAQUE beat pour
    que le style choisi s'applique à SA photo plutôt qu'à un visage
    inventé. Dépend du modèle/style — résultat pas garanti sur tous les
    styles (voir render/images.generate_first_frame).

    Un seul reel se rend à la fois (verrou global _REEL_RENDER_LOCK).

    Example:
      curl -X POST http://localhost:8080/api/v1/execute/async/reel-af.reel_text_to_reel \\
        -H 'Content-Type: application/json' \\
        -d '{"input":{"text":"...","art_style":"style3","mode":"brute","lang":"fr","voice_preset":"voice3"}}'
    """
    if "OPENROUTER_API_KEY" not in os.environ:
        return {"error": "OPENROUTER_API_KEY not set in env."}
    if not text or not text.strip():
        return {"error": "text is required and cannot be empty."}
    async with _REEL_RENDER_LOCK:
        return await _text_to_reel_locked(
            text, out_dir, art_style, mode, lang, voice_preset, person_photo,
        )


async def _text_to_reel_locked(
    text: str,
    out_dir: str | None = None,
    art_style: str = "",
    mode: str = "brute",
    lang: str = "",
    voice_preset: str = "",
    person_photo: str = "",
) -> dict:
    run_id = uuid.uuid4().hex[:8]
    out_path = (
        Path(out_dir) if out_dir else (Path.cwd() / "output" / f"text-{run_id}")
    )
    out_path.mkdir(parents=True, exist_ok=True)
    media_dir = out_path / "media"
    media_dir.mkdir(parents=True, exist_ok=True)

    app.cost_tracker.reset()
    cost_track.reset()

    timings: dict[str, float] = {}
    node = app.node_id
    app.note(
        f"reel-af text: starting run {run_id} (mode={mode})",
        tags=["reel", "text", "start"],
    )
    t_pipeline = time.time()

    if mode == "verbatim":
        # Aucune réécriture : découpe pure du texte collé, pas d'appel .ai().
        t = time.time()
        script = _script_from_verbatim_text(text)
        timings["compose"] = round(time.time() - t, 1)
        essence = {
            "core_claim": script["hook"][:200],
            "mechanism": script["payoff_line"][:200],
            "evidence": [script["hook"][:120]],
            "content_mode": "general",
            "domain": "verbatim",
        }
        chosen_hook = {"hookability": None}
    else:
        # mode == "brute" : le texte remplace l'essence ; hook + compose
        # tournent normalement (pipeline article privé de l'extraction).
        from reel_af.agents.extract import essence_from_text

        t = time.time()
        essence_obj = await essence_from_text(app, text)
        essence = essence_obj.model_dump()
        timings["extract"] = round(time.time() - t, 1)

        t = time.time()
        h_out = await app.call(f"{node}.reel_pick_hook", essence=essence, lang=lang)
        timings["hook"] = round(time.time() - t, 1)
        chosen_hook = h_out["hook_pick"]["chosen"]

        t = time.time()
        c_out = await app.call(
            f"{node}.reel_compose_script",
            essence=essence,
            chosen_hook=chosen_hook,
            lang=lang,
        )
        timings["compose"] = round(time.time() - t, 1)
        script = c_out["script"]

    final = await _render_downstream(
        node=node,
        essence=essence,
        script=script,
        out_path=out_path,
        media_dir=media_dir,
        run_id=run_id,
        timings=timings,
        art_style=art_style,
        lang=lang,
        voice_preset=voice_preset,
        person_photo=person_photo,
    )

    cost_report = cost_track.write(out_path, app.execution_cost)

    timings["total"] = round(time.time() - t_pipeline, 1)
    app.note(
        f"reel-af text: run {run_id} done → {final['video_path']}",
        tags=["reel", "text", "done"],
    )
    return {
        **final,
        "source": "text",
        "mode": mode,
        "hook": script["hook"],
        "hook_variant": script["hook_variant"],
        "hookability_score": chosen_hook.get("hookability"),
        "run_id": run_id,
        "timings_s": timings,
        "cost_usd": cost_report["total_cost_usd"],
    }


# ════════════════════════════════════════════════════════════════════
# ENTRY REASONER 2 — Topic → Reel
# ════════════════════════════════════════════════════════════════════


@reel.reasoner()
async def topic_to_reel(
    topic: str, out_dir: str | None = None, art_style: str = "", lang: str = "",
) -> dict:
    """Turn a topic string into a vertical viral reel.

    Internally runs an 8-node hunter cascade (4 parallel hunters →
    critic → 3 parallel narrators → pairwise judge) to produce a
    delayed-reveal narration, then the same shared downstream path as
    article_to_reel.

    ``art_style`` : nom d'un preset visuel (ex. "style1") pour A/B tester
    un style d'image sans redémarrer — voir render/images.py.
    ``lang`` : réservé pour la voix/surcouches en aval (synthesize_audio,
    plan_accents) — les hunters/narrator/judge restent en anglais pour
    l'instant (mode sujet non localisé, voir bon-stock/STYLE-FR.md).

    Example:
      curl -X POST http://localhost:8080/api/v1/execute/async/reel-af.reel_topic_to_reel \\
        -H 'Content-Type: application/json' \\
        -d '{"input":{"topic":"philosophy of mind","art_style":"style1"}}'
    """
    if "OPENROUTER_API_KEY" not in os.environ:
        return {"error": "OPENROUTER_API_KEY not set in env."}
    async with _REEL_RENDER_LOCK:
        return await _topic_to_reel_locked(topic, out_dir, art_style, lang)


async def _topic_to_reel_locked(
    topic: str, out_dir: str | None = None, art_style: str = "", lang: str = "",
) -> dict:
    run_id = uuid.uuid4().hex[:8]
    out_path = (
        Path(out_dir) if out_dir else (Path.cwd() / "output" / f"topic-{run_id}")
    )
    out_path.mkdir(parents=True, exist_ok=True)
    media_dir = out_path / "media"
    media_dir.mkdir(parents=True, exist_ok=True)

    # Un seul reel rendu à la fois (_REEL_RENDER_LOCK) → un accumulateur
    # global suffit pour capter le coût réel de CE run.
    app.cost_tracker.reset()
    cost_track.reset()

    timings: dict[str, float] = {}
    node = app.node_id
    app.note(
        f"reel-af topic: starting run {run_id} for topic={topic!r}",
        tags=["reel", "topic", "start"],
    )
    t_pipeline = time.time()

    # Phase 1 — 4 parallel hunters
    t = time.time()
    h_results = await asyncio.gather(
        app.call(f"{node}.reel_hunt_specific_figure", topic=topic),
        app.call(f"{node}.reel_hunt_reversal", topic=topic),
        app.call(f"{node}.reel_hunt_temporal", topic=topic),
        app.call(f"{node}.reel_hunt_cross_domain", topic=topic),
    )
    all_candidates: list[dict] = [
        c for batch in h_results for c in batch["candidates"]
    ]
    timings["hunt"] = round(time.time() - t, 1)

    # Phase 2 — critic picks top 3
    t = time.time()
    crit_out = await app.call(
        f"{node}.reel_pick_top_essences",
        topic=topic,
        candidates=all_candidates,
        n_top=3,
    )
    timings["critic"] = round(time.time() - t, 1)
    chosen_essences: list[dict] = crit_out["chosen_essences"]

    # Phase 3 — 3 narrators in parallel
    t = time.time()
    narr_out = await app.call(
        f"{node}.reel_write_narrations",
        essences=chosen_essences,
    )
    timings["narrate"] = round(time.time() - t, 1)
    scripts: list[dict] = narr_out["scripts"]

    # Phase 4 — judge picks winner
    t = time.time()
    verdict = await app.call(
        f"{node}.reel_pick_best_narration",
        topic=topic,
        scripts=scripts,
        essences=chosen_essences,
    )
    timings["judge"] = round(time.time() - t, 1)
    winner_idx = max(0, min(verdict["winner_idx"], len(scripts) - 1))
    winner_script = scripts[winner_idx]
    winner_essence = chosen_essences[winner_idx]

    # ── Map ConversationalScript → ScriptDraft for the downstream ─────
    # Beats/visuals/accents all operate on ScriptDraft; the topic
    # pipeline writes ConversationalScripts so we adapt the field
    # shapes (tease → hook, reveal-sentences → mechanism_lines, …).
    reveal_sentences = [
        s.strip()
        for s in re.split(r"(?<=[.!?])\s+", winner_script["reveal"].strip())
        if s.strip()
    ]
    if len(reveal_sentences) < 2:
        # ScriptDraft requires min_length=2 on mechanism_lines.
        reveal_sentences = (
            reveal_sentences + [winner_script.get("common_belief") or "."]
        )[:2]

    essence = {
        "core_claim": winner_essence["core_claim"],
        "mechanism": winner_essence["mechanism"],
        "evidence": winner_essence["evidence"],
        "content_mode": "general",  # topic-derived → conversational register
        "domain": winner_essence["domain"],
    }
    script = {
        "hook": winner_script["tease"],
        "hook_variant": "curiosity_gap",
        "mechanism_lines": reveal_sentences[:4],
        "payoff_line": winner_script["payoff"],
        "target_wpm": 180,
        "narration": winner_script["narration"],
    }

    final = await _render_downstream(
        node=node,
        essence=essence,
        script=script,
        out_path=out_path,
        media_dir=media_dir,
        run_id=run_id,
        timings=timings,
        art_style=art_style,
        lang=lang,
    )

    cost_report = cost_track.write(out_path, app.execution_cost)

    timings["total"] = round(time.time() - t_pipeline, 1)
    app.note(
        f"reel-af topic: run {run_id} done → {final['video_path']}",
        tags=["reel", "topic", "done"],
    )
    return {
        **final,
        "source": "topic",
        "topic": topic,
        "tease": winner_script["tease"],
        "reveal": winner_script["reveal"],
        "payoff": winner_script["payoff"],
        "common_belief": winner_script.get("common_belief"),
        "open_style": winner_script["open_style"],
        "chosen_essence": winner_essence,
        "winner_composite": verdict.get("composite_score"),
        "winner_why": verdict.get("why"),
        "all_candidates": all_candidates,
        "all_narrations": [s["narration"] for s in scripts],
        "run_id": run_id,
        "timings_s": timings,
        "cost_usd": cost_report["total_cost_usd"],
    }


# ════════════════════════════════════════════════════════════════════
# Shared downstream orchestrator
# ════════════════════════════════════════════════════════════════════


async def _render_downstream(
    *,
    node: str,
    essence: dict,
    script: dict,
    out_path: Path,
    media_dir: Path,
    run_id: str,
    timings: dict[str, float],
    art_style: str = "",
    lang: str = "",
    voice_preset: str = "",
    person_photo: str = "",
) -> dict:
    """audio → cards/beats (parallel) → visuals/accents (parallel) →
    videos → stitch. Used by both entry points."""

    # TTS — sentence-by-sentence
    t = time.time()
    a_out = await app.call(
        f"{node}.reel_synthesize_audio",
        narration=script["narration"],
        voice_tone="wonder",
        out_dir=str(media_dir),
        target_wpm=script["target_wpm"],
        lang=lang,
        voice_preset=voice_preset,
    )
    timings["tts"] = round(time.time() - t, 1)

    # Cards (subtitle layout) ∥ Beats (video planning)
    t = time.time()
    cards_task = asyncio.create_task(app.call(
        f"{node}.reel_pack_cards",
        word_timings=a_out["word_timings"],
    ))
    beats_task = asyncio.create_task(app.call(
        f"{node}.reel_plan_beats",
        script=script,
        audio_duration_s=a_out["duration_s"],
    ))
    cards_out, beats_out = await asyncio.gather(cards_task, beats_task)
    timings["plan"] = round(time.time() - t, 1)
    cards = cards_out["cards"]
    beats = beats_out["beats"]

    # Visuals ∥ Accents
    t = time.time()
    visuals_task = asyncio.create_task(app.call(
        f"{node}.reel_plan_visuals",
        beats=beats,
        essence=essence,
        spoken_narration=a_out["spoken_narration"],
    ))
    accents_task = asyncio.create_task(app.call(
        f"{node}.reel_plan_accents",
        beats=beats,
        essence=essence,
        lang=lang,
    ))
    v_out, ac_out = await asyncio.gather(visuals_task, accents_task)
    timings["visual_accent"] = round(time.time() - t, 1)

    # Videos
    t = time.time()
    g_out = await app.call(
        f"{node}.reel_generate_videos",
        beats=beats,
        visuals=v_out["visuals"],
        content_mode=essence["content_mode"],
        out_dir=str(out_path),
        art_style=art_style,
        person_photo=person_photo,
    )
    timings["media"] = round(time.time() - t, 1)

    # Stitch
    t = time.time()
    s_out = await app.call(
        f"{node}.reel_stitch_reel",
        beats=beats,
        artifacts=g_out["artifacts"],
        cards=cards,
        accents=ac_out["accents"],
        audio_path=a_out["audio_path"],
        out_dir=str(out_path),
        run_id=run_id,
    )
    timings["stitch"] = round(time.time() - t, 1)

    return {
        "video_path": s_out["video_path"],
        "duration_s": a_out["duration_s"],
        "narration": a_out["spoken_narration"],
        "voice_id": a_out["voice"],
        "beat_count": len(beats),
        "card_count": len(cards),
        "accent_count": sum(1 for a in ac_out["accents"] if a is not None),
    }


# ════════════════════════════════════════════════════════════════════
# Server
# ════════════════════════════════════════════════════════════════════


app.include_router(reel)


def _health() -> dict:
    return {"status": "ok", "service": "reel-af", "version": "1.0.0"}


from typing import cast as _cast  # noqa: E402

_cast(Any, app).add_api_route("/health", _health, methods=["GET"])


# ════════════════════════════════════════════════════════════════════
# Interface texte-vers-reel — servie par CET agent (port 8092), pas par
# le control-plane (image verrouillée, refuse tout Origin ≠
# http://localhost:8090 — voir CONSIGNE-CLAUDE-CODE-texte-vers-reel.md
# §2). Fichiers statiques + un petit proxy serveur-à-serveur vers le
# control-plane (jamais soumis au CORS du navigateur, contrairement à un
# fetch() direct depuis la page).
# ════════════════════════════════════════════════════════════════════

from starlette.requests import Request  # noqa: E402
from starlette.responses import FileResponse, JSONResponse  # noqa: E402
from starlette.staticfiles import StaticFiles  # noqa: E402

_STYLES_DIR = _PROJECT_ROOT / "styles"
if _STYLES_DIR.is_dir():
    _cast(Any, app).mount(
        "/styles", StaticFiles(directory=str(_STYLES_DIR)), name="styles",
    )

# Styles custom distillés depuis un mood board — bon-stock/ est monté EN
# DIRECT et INSCRIPTIBLE (voir docker-compose.yml, retiré le ":ro") pour que
# ce store survive sans reconstruction. Même dossier que
# render/images._CUSTOM_STYLES_DIR.
_CUSTOM_STYLES_DIR = _PROJECT_ROOT / "bon-stock" / "styles-custom"
_CUSTOM_STYLES_DIR.mkdir(parents=True, exist_ok=True)
_cast(Any, app).mount(
    "/styles-custom",
    StaticFiles(directory=str(_CUSTOM_STYLES_DIR)),
    name="styles-custom",
)

# Photo de la personne-sujet du reel (/texte, upload optionnel) — même
# dossier que render/images._PERSON_REFS_DIR.
_PERSON_REFS_DIR = _PROJECT_ROOT / "bon-stock" / "person-refs"
_PERSON_REFS_DIR.mkdir(parents=True, exist_ok=True)
_cast(Any, app).mount(
    "/person-refs",
    StaticFiles(directory=str(_PERSON_REFS_DIR)),
    name="person-refs",
)


def _texte_page() -> FileResponse:
    return FileResponse(str(_PROJECT_ROOT / "texte-vers-reel.html"))


_cast(Any, app).add_api_route("/texte", _texte_page, methods=["GET"])


async def _proxy_execute(reasoner: str, request: Request) -> JSONResponse:
    """Relais serveur-à-serveur : reçoit le POST same-origin du navigateur
    et le relaie vers l'API async du control-plane. Un appel serveur n'est
    jamais soumis au CORS (règle du navigateur, pas du serveur), donc ceci
    contourne le blocage 403 du control-plane sans toucher à son image
    verrouillée."""
    import aiohttp

    body = await request.json()
    target = (
        f"{os.getenv('AGENTFIELD_SERVER', 'http://localhost:8080')}"
        f"/api/v1/execute/async/reel-af.{reasoner}"
    )
    async with aiohttp.ClientSession() as session:
        async with session.post(target, json=body) as resp:
            data = await resp.json(content_type=None)
            return JSONResponse(data, status_code=resp.status)


_cast(Any, app).add_api_route(
    "/api/reel-af/execute/{reasoner}", _proxy_execute, methods=["POST"],
)


def _presets() -> dict:
    """Styles + voix pour l'interface texte-vers-reel.html — SOURCE UNIQUE
    côté Python (render/images.STYLE_UI_META, render/tts.VOICE_PRESETS) +
    les styles custom distillés depuis un mood board (bon-stock/styles-
    custom/*/preset.json). Ajouter un style ou une voix là-bas suffit ;
    l'interface le reflète sans jamais être retouchée."""
    from reel_af.render.images import STYLE_UI_META
    from reel_af.render.tts import VOICE_PRESETS

    styles = [
        {"id": key, **meta} for key, meta in STYLE_UI_META.items()
    ]
    for preset_file in sorted(_CUSTOM_STYLES_DIR.glob("*/preset.json")):
        try:
            data = json.loads(preset_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        style_id = data.get("id") or preset_file.parent.name
        styles.append({
            "id": style_id,
            "nom": data.get("nom", style_id),
            "bon": data.get("bon", ""),
            "pal": data.get("pal", []),
            "desc": data.get("desc", ""),
            "thumb": f"/styles-custom/{style_id}/thumb.jpg",
        })
    voices = [
        {"id": key, **meta} for key, meta in VOICE_PRESETS.items()
    ]
    return {"styles": styles, "voices": voices}


_cast(Any, app).add_api_route("/api/reel-af/presets", _presets, methods=["GET"])


def _extract_palette(images: list, n: int = 5) -> list[str]:
    """Couleurs dominantes (hex) d'une mosaïque réduite des refs — PIL
    quantize, déterministe (pas fiable de laisser le LLM inventer des hex)."""
    from PIL import Image as _PILImage

    mosaic = _PILImage.new("RGB", (64 * len(images), 64))
    for i, img in enumerate(images):
        mosaic.paste(img.resize((64, 64)), (i * 64, 0))
    quantized = mosaic.quantize(colors=n)
    palette = quantized.getpalette() or []
    colors = [tuple(palette[i : i + 3]) for i in range(0, min(len(palette), n * 3), 3)]
    return [f"#{r:02X}{g:02X}{b:02X}" for r, g, b in colors]


def _make_moodboard_thumb(images: list, dest: Path, width: int = 440) -> None:
    """Vignette = collage horizontal des refs, recadré ~440px de large,
    cohérent avec les vignettes des styles built-in (même logique de
    center-crop-to-cover que render/images._crop_to_9x16)."""
    from PIL import Image as _PILImage

    n = len(images)
    cell_w = max(1, width // n)
    height = cell_w * 16 // 9
    collage = _PILImage.new("RGB", (cell_w * n, height))
    for i, img in enumerate(images):
        w, h = img.size
        scale = max(cell_w / w, height / h)
        resized = img.resize((max(1, round(w * scale)), max(1, round(h * scale))))
        left = (resized.width - cell_w) // 2
        top = (resized.height - height) // 2
        cropped = resized.crop((left, top, left + cell_w, top + height))
        collage.paste(cropped, (i * cell_w, 0))
    dest.parent.mkdir(parents=True, exist_ok=True)
    collage.save(str(dest), format="JPEG", quality=88)


_MOODBOARD_MAX_REFS = 16
_MOODBOARD_MAX_FILES = 8


def _pdf_pages_to_images(data: bytes, dpi: int = 150, max_pages: int = _MOODBOARD_MAX_REFS) -> list:
    """Repli : une image PIL par PAGE rendue (capture de page entière).

    Utilisé seulement quand le PDF n'a AUCUNE image raster détectable par
    _pdf_images (contenu vectoriel, ou une seule image de fond par page
    déjà couverte par ce rendu) — sinon _pdf_images (ci-dessous) est
    strictement plus fidèle : une image par PHOTO réelle, pas par page."""
    import io

    import pymupdf  # nom moderne — "fitz" est l'alias historique, déprécié
    from PIL import Image as _PILImage

    pages = []
    doc = pymupdf.open(stream=data, filetype="pdf")
    mat = pymupdf.Matrix(dpi / 72, dpi / 72)
    for page in doc[:max_pages]:
        pix = page.get_pixmap(matrix=mat)
        pages.append(_PILImage.open(io.BytesIO(pix.tobytes("png"))).convert("RGB"))
    return pages


def _pdf_images(data: bytes, max_images: int = _MOODBOARD_MAX_REFS, min_px: int = 150) -> list:
    """Extrait TOUTES les images raster réellement intégrées au PDF, peu
    importe leur page ou leur position (un mood board a souvent plusieurs
    photos par page, en grille/collage) — contrairement à une capture de
    page qui noierait plusieurs photos distinctes dans UNE seule image
    composite et perdrait tout ce qui dépasse la Nième page.

    Déduplique par xref (même image réutilisée sur plusieurs pages) et
    ignore les tout petits éléments (puces, icônes, logos de pied de page)
    sous `min_px`. Repli sur un rendu de page si rien d'exploitable n'est
    trouvé (PDF purement vectoriel, par ex.)."""
    import io

    import pymupdf
    from PIL import Image as _PILImage

    doc = pymupdf.open(stream=data, filetype="pdf")
    seen_xrefs: set[int] = set()
    images: list = []
    for page in doc:
        for img_info in page.get_images(full=True):
            xref = img_info[0]
            if xref in seen_xrefs:
                continue
            seen_xrefs.add(xref)
            try:
                extracted = doc.extract_image(xref)
                img = _PILImage.open(io.BytesIO(extracted["image"])).convert("RGB")
            except Exception:  # noqa: BLE001
                continue
            if img.width < min_px or img.height < min_px:
                continue  # probablement une puce/icône/logo, pas une photo
            images.append(img)
            if len(images) >= max_images:
                return images
    return images or _pdf_pages_to_images(data, max_pages=max_images)


async def _moodboard_upload(request: Request) -> JSONResponse:
    """POST /api/reel-af/moodboard (multipart) — `nom` (optionnel) + 1..8
    fichiers `images` (JPEG/PNG/WEBP/… ou PDF — chaque image réellement
    intégrée au PDF devient une référence, voir _pdf_images) →
    distillation vision en UN preset de style réutilisable, écrit dans
    bon-stock/styles-custom/<id>/ (persiste sans reconstruction).

    N'entre PAS dans _REEL_RENDER_LOCK : la distillation est un appel court
    et indépendant d'un rendu de reel — elle n'a pas à attendre son tour
    derrière un reel en cours."""
    import io

    from PIL import Image as _PILImage, ImageOps as _ImageOps

    form = await request.form()
    nom_hint = str(form.get("nom") or "").strip()
    uploads = [v for v in form.getlist("images") if hasattr(v, "filename") and v.filename]
    if not uploads:
        return JSONResponse({"error": "Aucun fichier reçu."}, status_code=422)
    if len(uploads) > _MOODBOARD_MAX_FILES:
        return JSONResponse(
            {"error": f"{_MOODBOARD_MAX_FILES} fichiers maximum."}, status_code=422,
        )

    max_bytes = 10 * 1024 * 1024
    raw_uploads: list[tuple[str, bytes]] = []
    for up in uploads:
        data = await up.read()
        if len(data) > max_bytes:
            return JSONResponse(
                {"error": f"Fichier trop lourd ({up.filename}) — 10 Mo max."},
                status_code=422,
            )
        raw_uploads.append((up.filename or "", data))

    pil_images = []
    truncated = False
    for i, (filename, data) in enumerate(raw_uploads):
        is_pdf = filename.lower().endswith(".pdf") or data[:4] == b"%PDF"
        try:
            if is_pdf:
                remaining = _MOODBOARD_MAX_REFS - len(pil_images)
                found = _pdf_images(data, max_images=remaining + 1)  # +1 pour détecter le dépassement
                truncated = truncated or len(found) > remaining
                pil_images.extend(found[:remaining])
            else:
                img = _PILImage.open(io.BytesIO(data))
                img.verify()
                img = _PILImage.open(io.BytesIO(data))  # verify() invalide l'objet
                pil_images.append(_ImageOps.exif_transpose(img).convert("RGB"))
        except Exception:  # noqa: BLE001
            return JSONResponse(
                {"error": f"Fichier non reconnu comme image ou PDF ({filename})."},
                status_code=422,
            )
        if len(pil_images) >= _MOODBOARD_MAX_REFS:
            truncated = truncated or i + 1 < len(raw_uploads)
            break

    if not pil_images:
        return JSONResponse(
            {"error": "Aucune image exploitable (PDF vide ou purement vectoriel ?)."},
            status_code=422,
        )
    pil_images = pil_images[:_MOODBOARD_MAX_REFS]

    slug = re.sub(r"[^a-z0-9]+", "-", nom_hint.lower()).strip("-")[:24]
    style_id = f"mb-{slug or uuid.uuid4().hex[:6]}-{uuid.uuid4().hex[:4]}"
    style_dir = _CUSTOM_STYLES_DIR / style_id
    refs_dir = style_dir / "refs"
    refs_dir.mkdir(parents=True, exist_ok=True)

    ref_paths = []
    for i, img in enumerate(pil_images):
        p = refs_dir / f"ref-{i:02d}.jpg"
        img.save(str(p), format="JPEG", quality=90)
        ref_paths.append(p)

    try:
        from reel_af.agents.moodboard import distill_style

        distillation = await distill_style(app, ref_paths)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            {"error": f"Distillation échouée : {exc}"}, status_code=500,
        )

    pal = _extract_palette(pil_images)
    _make_moodboard_thumb(pil_images, style_dir / "thumb.jpg")

    preset = {
        "id": style_id,
        "english_prompt": distillation.english_prompt,
        "nom": nom_hint or distillation.nom,
        "bon": distillation.bon,
        "pal": pal,
        "desc": distillation.desc,
    }
    (style_dir / "preset.json").write_text(
        json.dumps(preset, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    return JSONResponse({
        **preset,
        "thumb": f"/styles-custom/{style_id}/thumb.jpg",
        "refs_used": len(pil_images),
        "truncated": truncated,
    })


_cast(Any, app).add_api_route(
    "/api/reel-af/moodboard", _moodboard_upload, methods=["POST"],
)


async def _person_photo_upload(request: Request) -> JSONResponse:
    """POST /api/reel-af/person-photo (multipart, champ `photo`) — UNE
    photo de la personne-sujet du reel. Enregistrée dans
    bon-stock/person-refs/<id>.jpg (monté en direct, persiste sans
    reconstruction) ; l'id retourné se passe en `person_photo` à
    text_to_reel, qui la joint en entrée (image-to-image) de CHAQUE beat —
    voir render/images.generate_first_frame."""
    import io

    from PIL import Image as _PILImage, ImageOps as _ImageOps

    form = await request.form()
    upload = form.get("photo")
    if not upload or not hasattr(upload, "filename") or not upload.filename:
        return JSONResponse({"error": "Aucune photo reçue."}, status_code=422)

    data = await upload.read()
    if len(data) > 10 * 1024 * 1024:
        return JSONResponse({"error": "Photo trop lourde — 10 Mo max."}, status_code=422)

    try:
        img = _PILImage.open(io.BytesIO(data))
        img.verify()
        img = _PILImage.open(io.BytesIO(data))  # verify() invalide l'objet
        img = _ImageOps.exif_transpose(img).convert("RGB")
    except Exception:  # noqa: BLE001
        return JSONResponse(
            {"error": "Fichier non reconnu comme image."}, status_code=422,
        )

    photo_id = uuid.uuid4().hex[:12]
    img.save(str(_PERSON_REFS_DIR / f"{photo_id}.jpg"), format="JPEG", quality=92)
    return JSONResponse({"id": photo_id, "url": f"/person-refs/{photo_id}.jpg"})


_cast(Any, app).add_api_route(
    "/api/reel-af/person-photo", _person_photo_upload, methods=["POST"],
)


def main() -> None:
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8002")),
        auto_port=False,
    )


if __name__ == "__main__":
    main()
