from flask import Flask, request, render_template, session, redirect, url_for
import pandas as pd
import os, math, uuid
import numpy as np
import plotly.graph_objects as go
import plotly.express as px

app = Flask(__name__)
app.secret_key = 'supersecretkey'
UPLOAD_FOLDER = os.path.join(os.getcwd(), 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

df_cache = {}  # 전역 캐시 선언

def ciede2000(L1, A1, B1, L2, A2, B2):
    C1 = math.sqrt(A1**2 + B1**2)
    C2 = math.sqrt(A2**2 + B2**2)
    Cm = (C1 + C2) / 2
    DL = L2 - L1
    DC = C2 - C1
    DA = A2 - A1
    DB = B2 - B1
    DH = math.sqrt(abs(DA**2 + DB**2 - DC**2))
    H1 = math.atan2(B1, A1)
    H2 = math.atan2(B2, A2)
    Hm = (H1 + H2) / 2
    T = 1 - 0.17 * math.cos(Hm - math.radians(30)) + 0.24 * math.cos(2 * Hm) + \
        0.32 * math.cos(3 * Hm + math.radians(6)) - 0.20 * math.cos(4 * Hm - math.radians(63))
    RT = -2 * math.sqrt(Cm**7 / (Cm**7 + 25**7)) * math.sin(math.radians(60) * math.exp(-((Hm - math.radians(275))**2) / (math.radians(25)**2)))
    return math.sqrt(DL**2 + (DC / (1 + 0.045 * Cm))**2 + (DH / (1 + 0.015 * Cm))**2 + RT * DC * DH)

def calculate_differences_vec(df, L, A, B):
    return [round(ciede2000(L, A, B, row['L'], row['a*'], row['b*']), 4) for _, row in df.iterrows()]

@app.route('/', methods=['GET', 'POST'])
def upload_and_process():
    graph_2d = graph_3d = None
    filt_cols = filt_data = None
    full_cols = full_data = None

    sheets = session.get('sheet_names')
    fp = session.get('file_path')
    sel = session.get('selected_sheet')
    L = A = B = 0.0
    L_thr, C_thr, h_thr, dE_thr = 1.0, 1.5, 3.0, 2.5

    if request.method == 'POST':
        if 'file' in request.files and request.files['file'].filename:
            f = request.files['file']
            ext = f.filename.rsplit('.', 1)[-1]
            name = f"{uuid.uuid4()}.{ext}"
            path = os.path.join(UPLOAD_FOLDER, name)
            f.save(path)
            xls = pd.ExcelFile(path)
            df_cache[path] = {s: xls.parse(s) for s in xls.sheet_names}
            session['sheet_names'] = xls.sheet_names
            session['file_path'] = path
            session['selected_sheet'] = None
            return redirect(url_for('upload_and_process'))

        if not fp or not sheets or not sel:
            return render_template('index.html', sheet_names=None, selected_sheet=None,
                                   graph_2d=None, filt_cols=None, filt_data=None,
                                   graph_3d=None, full_cols=None, full_data=None,
                                   L_thr=L_thr, C_thr=C_thr, h_thr=h_thr, dE_thr=dE_thr)

        form_s = request.form.get('sheet')
        if form_s:
            sel = form_s
            session['selected_sheet'] = sel
        elif not sel:
            sel = sheets[0]
            session['selected_sheet'] = sel

        df = df_cache.get(fp, {}).get(sel, pd.DataFrame())
        df.columns = df.columns.map(str).str.strip()

        for col in ['L', 'a*', 'b*', 'sR', 'sG', 'sB', 'HEX']:
            if col not in df:
                df[col] = '' if col == 'HEX' else 0

        try:
            L_thr = float(request.form.get('L_thr') or L_thr)
            C_thr = float(request.form.get('C_thr') or C_thr)
            h_thr = float(request.form.get('h_thr') or h_thr)
            dE_thr = float(request.form.get('dE_thr') or dE_thr)
        except ValueError:
            return "임계값은 숫자로 입력하세요."

        vals = request.form.get('input_values')
        act = request.form.get('action')
        if act and act.startswith('시트 값'):
            L, A, B = df['L'].mean(), df['a*'].mean(), df['b*'].mean()
        elif act and act.startswith('입력값') and vals:
            try:
                L, A, B = map(float, vals.split(','))
            except:
                return "L,a*,b* 형식 오류"
        else:
            L, A, B = df['L'].mean(), df['a*'].mean(), df['b*'].mean()

        mask = (df['L'] == L) & (df['a*'] == A) & (df['b*'] == B)
        if not mask.any():
            new_row = {c: '' for c in df.columns}
            new_row.update({'L': L, 'a*': A, 'b*': B})
            df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)

        df['dE'] = calculate_differences_vec(df, L, A, B)
        df['C'] = np.hypot(df['a*'], df['b*'])
        df['h'] = np.degrees(np.arctan2(df['b*'], df['a*']))
        df['ITA'] = df.apply(lambda r: math.degrees(math.atan((r['L']-50)/r['b*'])) if r['b*'] != 0 else 0, axis=1)

        input_C = math.hypot(A, B)
        input_h = math.degrees(math.atan2(B, A)) % 360

        full = df.sort_values('dE').reset_index(drop=True)
        full_cols = full.columns.tolist()
        full_data = full.to_dict('records')

        filt = full[(full['dE'] <= dE_thr) &
                    (full['L'].sub(L).abs() <= L_thr) &
                    (full['C'].sub(input_C).abs() <= C_thr) &
                    (full['h'].sub(input_h).abs() <= h_thr)]

        if filt.empty:
            filt = full[(full['L'] == L) & (full['a*'] == A) & (full['b*'] == B)]

        filt_cols = filt.columns.tolist()
        filt_data = filt.to_dict('records')

        # 2D 그래프 생성
        marker_colors = [('#'+str(r['HEX']).lstrip('#')) if r['HEX'] else 'blue' for r in filt_data]
        hover_texts = [r.get('벌크명', 'Input data') for r in filt_data]

        fig2 = go.Figure(data=[go.Scattergl(
            x=filt['h'], y=filt['ITA'], mode='markers',
            marker=dict(color=marker_colors, size=5, opacity=0.7),
            customdata=hover_texts,
            hovertemplate='%{customdata}<extra></extra>'
        )])
        fig2.update_layout(
            title="Filtered h vs ITA",
            xaxis=dict(range=[30, 90]),
            yaxis=dict(range=[-90, 90]),
            plot_bgcolor='#FBFBFB', paper_bgcolor='#FBFBFB',
            shapes=[
                dict(type='line', x0=30, x1=90, y0=0, y1=0, line=dict(color='black', width=1)),
                dict(type='line', x0=30, x1=30, y0=-90, y1=90, line=dict(color='black', width=1))
            ]
        )
        graph_2d = fig2.to_html(full_html=False, include_plotlyjs='cdn')

        # 3D 그래프 생성
        marker_colors_3d = [
            'blue' if (r['L'] == L and r['a*'] == A and r['b*'] == B)
            else f"rgb({r['sR']},{r['sG']},{r['sB']})"
            for r in full_data
        ]
        fig3 = go.Figure(data=[go.Scatter3d(
            x=full['a*'], y=full['b*'], z=full['L'],
            mode='markers',
            marker=dict(size=3.5, opacity=0.7, color=marker_colors_3d)
        )])
        fig3.update_layout(title="3D Color Scatter", width=600, height=800)
        graph_3d = fig3.to_html(full_html=False, include_plotlyjs='cdn')

    return render_template('index.html',
        sheet_names=sheets, selected_sheet=sel,
        graph_2d=graph_2d, filt_cols=filt_cols, filt_data=filt_data,
        graph_3d=graph_3d, full_cols=full_cols, full_data=full_data,
        L_thr=L_thr, C_thr=C_thr, h_thr=h_thr, dE_thr=dE_thr)

