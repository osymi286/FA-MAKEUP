from flask import Flask, request, render_template, session, redirect, url_for
import pandas as pd
import os
import plotly.graph_objects as go
import math
import uuid

app = Flask(__name__)
app.secret_key = 'supersecretkey'

UPLOAD_FOLDER = os.path.join(os.getcwd(), 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def ciede2000(L1, A1, B1, L2, A2, B2):
    C1 = math.sqrt(A1**2 + B1**2)
    C2 = math.sqrt(A2**2 + B2**2)
    Cm = (C1 + C2) / 2
    DL = L2 - L1
    DC = C2 - C1
    DA = A2 - A1
    DB = B2 - B1
    DH2 = DA**2 + DB**2 - DC**2
    DH = math.sqrt(abs(DH2))
    H1 = math.atan2(B1, A1)
    H2 = math.atan2(B2, A2)
    Hm = (H1 + H2) / 2
    T = 1 - 0.17 * math.cos(Hm - math.radians(30)) + \
        0.24 * math.cos(2 * Hm) + \
        0.32 * math.cos(3 * Hm + math.radians(6)) - \
        0.20 * math.cos(4 * Hm - math.radians(63))
    RT = -2 * math.sqrt(Cm**7 / (Cm**7 + 25**7)) * \
         math.sin(math.radians(60) * math.exp(-((Hm - math.radians(275))**2) / (math.radians(25)**2)))
    return math.sqrt(
        DL**2
        + (DC / (1 + 0.045 * Cm))**2
        + (DH / (1 + 0.015 * Cm))**2
        + RT * DC * DH
    )

def calculate_differences(df, input_L, input_A, input_B):
    diffs = []
    for _, row in df.iterrows():
        diffs.append(round(
            ciede2000(input_L, input_A, input_B, row['L'], row['a*'], row['b*']),
            4
        ))
    return diffs

@app.route('/', methods=['GET', 'POST'])
def upload_and_process():
    graph_html    = None
    table_columns = None
    table_data    = None

    sheet_names    = session.get('sheet_names')
    file_path      = session.get('file_path')
    selected_sheet = session.get('selected_sheet')
    input_l = input_a = input_b = 0.0

    if request.method == 'POST':
        # 1) 파일 업로드
        if 'file' in request.files and request.files['file'].filename:
            f = request.files['file']
            ext = f.filename.rsplit('.', 1)[-1]
            unique_name = f"{uuid.uuid4()}.{ext}"
            save_path   = os.path.join(UPLOAD_FOLDER, unique_name)
            f.save(save_path)

            xls = pd.ExcelFile(save_path)
            session['sheet_names']    = xls.sheet_names
            session['file_path']      = save_path
            session['selected_sheet'] = None
            return redirect(url_for('upload_and_process'))

        # 2) 파일/시트 정보 없으면 빈 화면
        if not file_path or not sheet_names:
            return render_template('index.html',
                                   sheet_names=None,
                                   selected_sheet=None,
                                   graph_html=None,
                                   table_columns=None,
                                   table_data=None)

        # 3) 시트 선택 유지 또는 기본 지정
        form_sheet = request.form.get('sheet')
        if form_sheet:
            selected_sheet = form_sheet
            session['selected_sheet'] = selected_sheet
        elif not selected_sheet:
            selected_sheet = sheet_names[0]
            session['selected_sheet'] = selected_sheet

        # 4) 입력값 파싱
        input_vals = request.form.get('input_values')
        action     = request.form.get('action')

        xls = pd.ExcelFile(file_path)
        if selected_sheet and xls:
            df = xls.parse(selected_sheet)
            df.columns = df.columns.map(str).str.strip()

            # 필수 컬럼 확보
            for c in ['L', 'a*', 'b*', 'sR', 'sG', 'sB', 'HEX']:
                if c not in df.columns:
                    df[c] = '' if c == 'HEX' else 0

            # 입력값 결정
            if action == "시트 값으로 그래프 보기":
                input_l = df['L'].mean()
                input_a = df['a*'].mean()
                input_b = df['b*'].mean()
            elif action == "입력값 위치 확인" and input_vals:
                try:
                    input_l, input_a, input_b = map(float, input_vals.split(','))
                except ValueError:
                    return "L, a, b 값을 제대로 입력하세요. 예: 50,0,0"
            else:
                input_l = df['L'].mean()
                input_a = df['a*'].mean()
                input_b = df['b*'].mean()

            # 입력값이 없으면 새 행 추가
            mask = (df['L'] == input_l) & (df['a*'] == input_a) & (df['b*'] == input_b)
            if not mask.any():
                new = {col: '' for col in df.columns}
                new.update({'L': input_l, 'a*': input_a, 'b*': input_b})
                df = pd.concat([df, pd.DataFrame([new])], ignore_index=True)

            # dE 계산 및 추가
            df['dE'] = calculate_differences(df, input_l, input_a, input_b)

            # dE 오름차순 정렬
            df_sorted = df.sort_values('dE', ascending=True).reset_index(drop=True)

            # 테이블 데이터 준비
            table_columns = df_sorted.columns.tolist()
            table_data    = df_sorted.to_dict(orient='records')

            # 3D 그래프 생성 (입력값은 파란색)
            colors = [
                'blue' if (r['L'] == input_l and r['a*'] == input_a and r['b*'] == input_b)
                else f"rgb({r['sR']},{r['sG']},{r['sB']})"
                for r in table_data
            ]
            fig = go.Figure(data=[go.Scatter3d(
                x=df_sorted['a*'],
                y=df_sorted['b*'],
                z=df_sorted['L'],
                mode='markers',
                marker=dict(size=3, opacity=0.9, color=colors)
            )])
            fig.update_layout(
                title='Highlight Specific Points',
                width=700, height=700, autosize=False,
                scene=dict(
                    xaxis_title='a*',
                    yaxis_title='b*',
                    zaxis_title='L'
                )
            )
            graph_html = fig.to_html(
                full_html=False,
                include_plotlyjs='cdn',
                config={'responsive': False}
            )

    # GET/POST 모두 여기로 렌더
    return render_template('index.html',
                           sheet_names=sheet_names,
                           selected_sheet=selected_sheet,
                           graph_html=graph_html,
                           table_columns=table_columns,
                           table_data=table_data)

if __name__ == '__main__':
    app.run(debug=True)
