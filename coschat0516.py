from flask import Flask, request, render_template, session, redirect, url_for
import pandas as pd
import numpy as np
import os, math, uuid
import plotly.graph_objects as go
import plotly.express as px

app = Flask(__name__)
app.secret_key = 'supersecretkey'
UPLOAD_FOLDER = os.path.join(os.getcwd(), 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
df_cache = {}

def ciede2000(L1,A1,B1,L2,A2,B2):
    C1=np.sqrt(A1**2+B1**2); C2=np.sqrt(A2**2+B2**2); Cm=(C1+C2)/2
    DL=L2-L1; DC=C2-C1; DA=A2-A1; DB=B2-B1
    DH=np.sqrt(np.abs(DA**2+DB**2-DC**2))
    H1=np.arctan2(B1,A1); H2=np.arctan2(B2,A2); Hm=(H1+H2)/2
    T=1-0.17*np.cos(Hm-np.radians(30))+0.24*np.cos(2*Hm)+0.32*np.cos(3*Hm+np.radians(6))-0.20*np.cos(4*Hm-np.radians(63))
    RT=-2*np.sqrt(Cm**7/(Cm**7+25**7))*np.sin(np.radians(60)*np.exp(-((Hm-np.radians(275))**2)/(np.radians(25)**2)))
    return np.sqrt(DL**2 + (DC/(1+0.045*Cm))**2 + (DH/(1+0.015*Cm))**2 + RT*DC*DH)

def calculate_differences_vec(df, L, A, B):
    return ciede2000(L, A, B, df['L'].values, df['a*'].values, df['b*'].values)

@app.route('/', methods=['GET','POST'])
def upload_and_process():
    graph_2d = graph_3d = None
    filt_cols = filt_data = None
    full_cols = full_data = None

    sheets = session.get('sheet_names')
    fp     = session.get('file_path')
    sel    = session.get('selected_sheet')
    L=A=B = 0.0
    L_thr, C_thr, h_thr, dE_thr = 1.0, 1.5, 3.0, 2.5

    if request.method == 'POST':
        if 'file' in request.files and request.files['file'].filename:
            f = request.files['file']
            ext = f.filename.rsplit('.',1)[-1]
            name = f"{uuid.uuid4()}.{ext}"
            path = os.path.join(UPLOAD_FOLDER, name)
            f.save(path)
            xls = pd.ExcelFile(path)
            df_cache[path] = {s: xls.parse(s) for s in xls.sheet_names}
            session['sheet_names'] = xls.sheet_names
            session['file_path'] = path
            session['selected_sheet'] = None
            return redirect(url_for('upload_and_process'))

        if not fp or not sheets:
            return render_template('index.html')

        form_s = request.form.get('sheet')
        if form_s:
            sel = form_s
            session['selected_sheet'] = sel
        elif not sel:
            sel = sheets[0]
            session['selected_sheet'] = sel
        df = df_cache.get(fp, {}).get(sel, pd.DataFrame())
        df.columns = df.columns.map(str).str.strip()

        try:
            L_thr  = float(request.form.get('L_thr')  or L_thr)
            C_thr  = float(request.form.get('C_thr')  or C_thr)
            h_thr  = float(request.form.get('h_thr')  or h_thr)
            dE_thr = float(request.form.get('dE_thr') or dE_thr)
        except ValueError:
            return "임계값은 숫자로 입력하세요."

        vals = request.form.get('input_values')
        act  = request.form.get('action')
        if act and act.startswith('시트 값'):
            L, A, B = df['L'].mean(), df['a*'].mean(), df['b*'].mean()
        elif act and act.startswith('입력값') and vals:
            try:
                L, A, B = map(float, vals.split(','))
            except:
                return "L,a*,b* 형식 오류"
        else:
            L, A, B = df['L'].mean(), df['a*'].mean(), df['b*'].mean()

        mask = (df['L']==L)&(df['a*']==A)&(df['b*']==B)
        if not mask.any():
            new = {c: '' for c in df.columns}
            new.update({'L':L,'a*':A,'b*':B})
            df = pd.concat([df, pd.DataFrame([new])], ignore_index=True)

        df['dE'] = calculate_differences_vec(df, L, A, B)
        df['C']  = np.hypot(df['a*'], df['b*'])
        df['h']  = np.degrees(np.arctan2(df['b*'], df['a*']))
        df['ITA']= df.apply(lambda r: math.degrees(math.atan((r['L']-50)/r['b*'])) if r['b*']!=0 else 0, axis=1)

        input_C = np.hypot(A,B)
        input_h = np.degrees(np.arctan2(B, A)) % 360

        full = df.sort_values('dE').reset_index(drop=True)
        full_cols = full.columns.tolist()
        full_data = full.to_dict('records')

        filt = full[
            (full['dE']<=dE_thr) &
            (full['L'].sub(L).abs()<=L_thr) &
            (full['C'].sub(input_C).abs()<=C_thr) &
            (full['h'].sub(input_h).abs()<=h_thr)
        ]
        if filt.empty:
            filt = full[(full['L']==L)&(full['a*']==A)&(full['b*']==B)]
        filt_cols = filt.columns.tolist()
        filt_data = filt.to_dict('records')

        marker_colors_2d = []
        hover_texts = []
        for rec in filt_data:
            hexv = str(rec.get('HEX') or '').lstrip('#')
            marker_colors_2d.append('#'+hexv if hexv else 'blue')
            hover_texts.append(rec.get('벌크명') or 'Input data')

        fig2 = go.Figure(data=[go.Scattergl(
            x=filt['h'], y=filt['ITA'], mode='markers',
            marker=dict(color=marker_colors_2d, size=5, opacity=0.7),
            customdata=hover_texts, hovertemplate='%{customdata}<extra></extra>'
        )])
        fig2.update_layout(
            title="Filtered h vs ITA",
            width=700, height=800,
            plot_bgcolor='#FBFBFB', paper_bgcolor='#FBFBFB',
            xaxis=dict(range=[30,90], autorange=False, fixedrange=True),
            yaxis=dict(range=[-90,90], autorange=False, fixedrange=True),
            shapes=[
                dict(type='line', x0=30,x1=90,y0=0,y1=0,line=dict(color='black',width=1)),
                dict(type='line', x0=30,x1=30,y0=-90,y1=90,line=dict(color='black',width=1))
            ]
        )
        graph_2d = fig2.to_html(full_html=False, include_plotlyjs='cdn')

        cols3 = [
            'blue' if (r['L']==L and r['a*']==A and r['b*']==B)
            else f"rgb({r['sR']},{r['sG']},{r['sB']})"
            for r in full_data
        ]
        fig3 = go.Figure(data=[go.Scatter3d(
            x=full['a*'], y=full['b*'], z=full['L'],
            mode='markers', marker=dict(size=3.5, opacity=0.7, color=cols3)
        )])
        fig3.update_layout(title="3D Color Scatter", width=600, height=800)
        graph_3d = fig3.to_html(full_html=False, include_plotlyjs='cdn')

    return render_template('index.html',
        sheet_names=sheets, selected_sheet=sel,
        graph_2d=graph_2d, filt_cols=filt_cols, filt_data=filt_data,
        graph_3d=graph_3d, full_cols=full_cols, full_data=full_data,
        L_thr=L_thr, C_thr=C_thr, h_thr=h_thr, dE_thr=dE_thr
    )
