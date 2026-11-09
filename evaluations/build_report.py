#!/usr/bin/env python3
"""Build GitHub-readable result tables and an optional plot from public CSVs."""
from __future__ import annotations
import argparse
import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "evaluations/results"
DOCS = ROOT / "docs"


def read(name):
    with (RESULTS / name).open() as handle:
        return list(csv.DictReader(handle))


def num(value, digits=2, scale=1):
    return f"{float(value) * scale:.{digits}f}" if value not in (None, "") else "—"


def count(value):
    return f"{int(value):,}"


def table(headers, rows):
    def cell(value):
        return str(value).replace("|", "\\|")
    return "| " + " | ".join(headers) + " |\n| " + " | ".join("---" for _ in headers) + " |\n" + "\n".join("| " + " | ".join(map(cell, row)) + " |" for row in rows) + "\n"


def label(row):
    name = row['model'].split('/')[-1]
    return f"{name} · {row['modality'].replace('_', '+')}"


def build():
    configs = read("configurations.csv")
    by_id = {row["config_id"]: row for row in configs}
    judges = read("judge-scores.csv")
    intro = "[Evaluation overview](evaluation.md) · [Judge scores](evaluation-judges.md) · [Runtime and inventory](evaluation-models.md) · [Prompt experiments](evaluation-prompts.md)\n\n"
    lines = ["# Model inventory and runtime results\n\n", intro,
             "Generated from the [public aggregate CSV](../evaluations/results/configurations.csv). All 46 normalized configurations are included, including failed and partial runs. `N` counts persisted generation records, including reference/teacher generations; it is not a count of independent examples or API attempts.\n\n",
             "Runtime groups can combine sessions on different machines/settings. Latency is recorded wall-clock generation latency, not decode throughput. Mean/median/p95 use successful records with positive recorded latency; missing timing stays blank. Do not read these as a hardware-controlled speed leaderboard.\n\n",
             "## Inventory and reliability\n\n",
             table(["ID", "Recorded model / variant", "Runtime", "Mode", "N", "Succeeded", "Failed", "Other", "Schema valid %"],
                   [[r['config_id'], f"`{r['model']}`", r['runtime'], r['modality'].replace('_','+'), count(r['records']), count(r['succeeded']), count(r['failed']), r['other'], num(r['schema_valid_rate'],1,100)] for r in configs]),
             "\nOne HRM local-file alias was merged into its Hugging Face identifier. GGUF/MLX packaging, quantization and prompt variants collapse to base identities for the headline count; the configuration rows retain those distinctions. Qwen3-8B had 200 failed records and no successful generation. The other 24 local identities had at least one success; this includes small smoke runs, not just full benchmark runs.\n\n",
             "## Recorded latency and token use\n\n",
             table(["ID", "Timed successes", "Mean s", "Median s", "p95 s", "Mean input tokens", "Mean output tokens", "Recorded tokens"],
                   [[r['config_id'],count(r['timed_successes']),num(r['mean_latency_ms'],2,.001),num(r['p50_latency_ms'],2,.001),num(r['p95_latency_ms'],2,.001),num(r['mean_input_tokens'],0),num(r['mean_output_tokens'],0),count(r['total_recorded_tokens'])] for r in configs]),
             "\n[Per-level results](../evaluations/results/generation-levels.csv) · [Recorded runtime metadata](../evaluations/results/runtime-metadata.csv) · [All stored metrics](../evaluations/results/stored-metrics.csv)\n\n",
             "The metadata records Apple M5 Pro / 48 GB for some macOS runs. Earlier Windows runs do not have equivalent hardware metadata, so missing entries must not be inferred. Estimated cost is available only for a subset of records; it is retained in CSV as an historical estimate, not current pricing.\n"]
    (DOCS / 'evaluation-models.md').write_text(''.join(lines))

    lines = ["# LLM judge results\n\n", intro,
             "These are retrospective, model-judged scores on private activity evidence. Rows have different sample counts and sometimes different source subsets, prompt settings, and hierarchy levels. They are not a controlled leaderboard or human-validated accuracy scores. All configurations present in each completed judge cohort are shown, with failures retained.\n\n",
             "`Final` uses the original 0–100 scale. Faithfulness, coverage, precision, usefulness, noise and hallucination rate use 0–1. A dash means not recorded. CSV columns ending in `_n` give each metric's non-null denominator. Aggregation is the arithmetic mean over successful judgments; failed judgments never become zero quality scores.\n\n"]
    for run, suite, judge in sorted({(r['run'],r['suite'],r['judge']) for r in judges}, key=lambda k: ({'reference':0,'source_grounded':1,'automation':2}[k[1]],k[0],k[2])):
        rows = [r for r in judges if (r['run'],r['suite'],r['judge']) == (run,suite,judge)]
        lines += [f"## {suite.replace('_',' ').title()} · {judge} · {run}\n\n"]
        if suite == 'automation':
            lines += ["These scores describe inferred workflow opportunities, **not summary accuracy or demonstrated time savings**. Two historical cohorts overlap; do not sum them as independent tasks. Behavioral and mental-state outputs are excluded from the public data.\n\n",
                      table(["ID", "Configuration", "N ok", "Failed", "Final", "Automation", "AI delegation", "Shortcuts", "Repetition"],
                            [[r['config_id'],label(by_id[r['config_id']]),count(r['succeeded']),r['failed'],num(r['final_score']),num(r['automation_opportunity_score']),num(r['ai_delegation_score']),num(r['shortcut_opportunity_score']),num(r['repetition_score'])] for r in rows])]
        else:
            if suite == 'reference':
                lines += ["GPT-5.4 text+image is a **reference-model control**, not an independent candidate result: comparison against its own silver labels explains its near-perfect agreement. The mixed first-pass run is split by each result's actual judge model.\n\n"]
            lines += [table(["ID", "Configuration", "N ok", "Failed", "Final", "Faithful", "Coverage", "Precision", "Useful", "Noise", "Hallucination"],
                            [[r['config_id'],label(by_id[r['config_id']]) + (' **control**' if suite=='reference' and by_id[r['config_id']]['model']=='gpt-5.4' and by_id[r['config_id']]['modality']=='text_image' else ''),count(r['succeeded']),r['failed'],num(r['final_score']),num(r['faithfulness_score']),num(r['coverage_score']),num(r['precision_score']),num(r['usefulness_score']),num(r['noise_score']),num(r['hallucination_rate'])] for r in rows])]
        lines += ['\n']
    lines += ["[All judge scores, claim counts and denominators](../evaluations/results/judge-scores.csv) · [Per-level judge results](../evaluations/results/judge-levels.csv) · [Run totals](../evaluations/results/judge-runs.csv)\n"]
    (DOCS/'evaluation-judges.md').write_text(''.join(lines))

    titles = {'qwen36-27b-full50':'Qwen3.6-27B · initial sweep','qwen35-4b-full50':'Qwen3.5-4B · initial sweep','qwen35-4b-followup50':'Qwen3.5-4B · follow-up sweep','gemma4-12b-full50':'Gemma 4 12B experiment · MLX runner'}
    lines = ["# Prompt regression experiments\n\n", intro,
             "Four retained 50-card sweeps compare prompt variants on the same source-ID set **within each sweep**. All variants are shown, including regressions. These are development/tuning samples, not a held-out test set. Baseline rows labeled `default_existing` reuse stored outputs; missing fresh timing is not zero latency. The experiment groups are separate from the 29 base-identity database count. The Gemma group uses the historical directory/runner label; the per-card file does not independently record the model ID.\n\n",
             "The [original scoring implementation](../evaluations/prompt_metrics.py) combines lexical similarity and structural checks: 22% headline similarity + 38% summary similarity + 20% field agreement + 10% evidence-token overlap + 8% non-collapse heuristic + 2% confidence-range heuristic. It is **not semantic accuracy or an LLM-judge score**.\n\n",
             "SequenceMatcher measures normalized character-sequence similarity. Field agreement combines exact categorical matches and lexical overlap against silver output. The non-collapse score penalizes missing/duplicated fields, copied titles and instruction leakage. Confidence-range checks do not establish calibration.\n\n"]
    for name, title in titles.items():
        rows = read(f'prompts/{name}.csv')
        lines += [f"## {title}\n\n",
                  table(["Prompt variant", "N", "Combined", "Headline", "Summary", "Fields", "Evidence", "Non-collapse", "Parse %"],
                        [[f"`{r['variant']}`",r['n'],num(r['combined'],4),num(r['headline_sim'],4),num(r['summary_sim'],4),num(r['field_score'],4),num(r['evidence_overlap'],4),num(r['noncollapse'],4),num(r['parse_ok_rate'],0,100)] for r in rows]),
                  f"\n[Numeric results and timing](../evaluations/results/prompts/{name}.csv). Source-set equality was checked during export; private source IDs and activity text are omitted.\n\n"]
    lines += ["## What these experiments establish\n\nThe retained sweeps show an iterative process: choose a fixed sample, compare variants, inspect failure modes, retain the full result table, and run broader evaluation for selected variants. Some changes reduce the heuristic score. A prompt selected on these samples needs a separate holdout and source-grounded judgment before claiming a general quality gain.\n\nThe database also contains later full-run prompt variants for Qwen3.5-0.8B and Qwen3.5-4B. Their aggregate judge scores are in the main result tables, but their input-snapshot hashes differ from the original runs. A difference between those aggregate scores is not a clean prompt-only causal effect.\n"]
    (DOCS/'evaluation-prompts.md').write_text(''.join(lines))


def plot():
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    configs = {r['config_id']: r for r in read('configurations.csv')}
    rows = [r for r in read('judge-scores.csv') if r['suite']=='source_grounded']
    rows.sort(key=lambda r:(configs[r['config_id']]['base_model'].lower(), configs[r['config_id']]['modality']))
    plt.rcParams.update({'font.family':'DejaVu Sans','svg.fonttype':'none','svg.hashsalt':'workday-lens-evaluation-v1','font.size':11})
    fig, ax = plt.subplots(figsize=(13.5,10.1),facecolor='#fcfaf5')
    ax.set_facecolor('#fcfaf5')
    y = list(range(len(rows)))
    ax.barh([i-.17 for i in y],[float(r['faithfulness_score']) for r in rows],height=.29,color='#3d5f5a',label='Faithfulness')
    ax.barh([i+.17 for i in y],[float(r['coverage_score']) for r in rows],height=.29,color='#d89441',label='Coverage')
    names = [f"{configs[r['config_id']]['base_model']}  ·  {configs[r['config_id']]['modality'].replace('_','+')}" for r in rows]
    ax.set_yticks(y,names)
    ax.invert_yaxis()
    ax.set_xlim(0,1)
    ax.set_xlabel('Mean source-grounded judge score · 0–1')
    ax.grid(axis='x',alpha=.15)
    ax.set_axisbelow(True)
    ax.tick_params(axis='y',length=0,pad=12)
    for spine in ax.spines.values():spine.set_visible(False)
    for i,r in enumerate(rows):
        ax.text(1.025,i,f"n = {int(r['succeeded']):,}",va='center',fontsize=10,color='#686159',transform=ax.get_yaxis_transform())
    ax.legend(loc='upper center',bbox_to_anchor=(.5,1.075),ncol=2,frameon=False)
    fig.text(.035,.965,'Workday Lens · source-grounded evaluation',fontsize=24,fontweight='bold',color='#282b28')
    fig.text(.035,.927,'8,097 completed judgments · GPT-5.4-mini · all 16 configurations in this cohort',fontsize=12,color='#686159')
    fig.text(.035,.055,'Historical results, not a controlled leaderboard: sample sizes, source subsets and modalities differ.',fontsize=11,color='#686159')
    fig.text(.035,.032,'Raw activity stays private. Full scores, failures, rubrics and aggregation code are published in the repository.',fontsize=11,color='#686159')
    fig.subplots_adjust(left=.39,right=.88,top=.845,bottom=.12)
    for extension in ['svg','png']:
        fig.savefig(DOCS/f'images/evaluation-source-grounded.{extension}',dpi=140,facecolor=fig.get_facecolor(),metadata={'Date':None} if extension=='svg' else None)
    svg = DOCS/'images/evaluation-source-grounded.svg'
    svg.write_text('\n'.join(line.rstrip() for line in svg.read_text().splitlines()) + '\n')
    plt.close(fig)


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plot',action='store_true',help='Requires matplotlib; tables use only the standard library')
    args=parser.parse_args()
    build()
    if args.plot:plot()
