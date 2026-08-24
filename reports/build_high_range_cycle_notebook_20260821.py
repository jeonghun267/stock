from pathlib import Path

import nbformat as nbf
from nbclient import NotebookClient

root = Path(__file__).resolve().parents[1]
notebook_path = root / "REPORTS" / "high_range_cycle_backtest_20260821.ipynb"
nb = nbf.v4.new_notebook()
nb["cells"] = [
    nbf.v4.new_markdown_cell(
        "# 고저폭 재순환 가설 백테스트\n\n"
        "## tl;dr\n"
        "[HYPOTHETICAL] 현재 정의의 주간 고저폭 재순환 필터는 기준 조건을 개선하지 못했다. 실전 배선 근거로 사용하지 않는다."
    ),
    nbf.v4.new_markdown_cell(
        "## Context & Methods\n\n"
        "20일 상승추세에서 과거 3~8거래일 고저폭, 2일 변동성 수축, MA20 저점 지지 후 다음 날 시가 진입을 검사한다. "
        "왕복비용 0.47%를 포함하며 생산 진입·청산 재생이 아닌 EOD 연구다."
    ),
    nbf.v4.new_code_cell(
        "import json\n"
        "from pathlib import Path\n"
        "import pandas as pd\n"
        "root = Path.cwd().parent if Path.cwd().name.upper() == 'REPORTS' else Path.cwd()\n"
        "result_path = root / 'data' / 'research_reports' / 'high_range_cycle_backtest_20260821.json'\n"
        "result = json.loads(result_path.read_text(encoding='utf-8'))\n"
        "assert result['provenance'] == '[HYPOTHETICAL]'\n"
        "{'rows': result['source_rows'], 'codes': result['unique_codes'], 'period': (result['date_min'], result['date_max'])}"
    ),
    nbf.v4.new_markdown_cell("## Results"),
    nbf.v4.new_code_cell(
        "comparison = pd.DataFrame({\n"
        "    'baseline': result['baseline'],\n"
        "    'cycle_10pct': result['main_threshold'],\n"
        "}).T\n"
        "comparison"
    ),
    nbf.v4.new_code_cell(
        "pd.DataFrame(result['cycle_threshold_sensitivity']).T[[\n"
        "    'signals', 'mean_net_1d_pct', 'mean_net_3d_pct', 'mean_net_5d_pct',\n"
        "    'win_rate_net_5d_pct'\n"
        "]]"
    ),
    nbf.v4.new_markdown_cell(
        "## Takeaways\n\n"
        "- 세 임계값 민감도에서 결론이 바뀌지 않았다.\n"
        "- 고저폭 반복만으로 저점을 예측하는 조건은 채택하지 않는다.\n"
        "- 장중 수급 반전과 상대강도를 포함한 생산경로 재생 전에는 실전 조건으로 승격하지 않는다."
    ),
]
nb["metadata"]["kernelspec"] = {"display_name": "Python 3", "language": "python", "name": "python3"}
nbf.write(nb, notebook_path)
NotebookClient(nb, timeout=60, kernel_name="python3").execute(cwd=str(root))
nbf.write(nb, notebook_path)
print(notebook_path)
