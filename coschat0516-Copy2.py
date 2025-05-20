from flask import Flask, request, render_template, session, redirect, url_for
import pandas as pd
import os, math, uuid
import plotly.graph_objects as go
import plotly.express as px

app = Flask(__name__)
app.secret_key = 'supersecretkey'

UPLOAD_FOLDER = os.path.join(os.getcwd(), 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def ciede2000(L1,A1,B1,L2,A2,B2):
    C1=math.sqrt(A1**2+B1**2); C2=math.sqrt(A2**2+B2**2); Cm=(C1+C2)/2
    DL=L2-L1; DC=C2-C1; DA=A2-A1; DB=B2-B1
    DH=math.sqrt(abs(DA**2+DB**2-DC**2))
    H1=math.atan2(B1,A1); H2=math.atan2(B2,A2); Hm=(H1+H2)/2
    T=1-0.17*math.cos(Hm-math.radians(30))+0.24*math.cos(2*Hm)+0.32*math.cos(3*Hm+math.radians(6))-0.20*math.cos(4*Hm-math.radians(63))
    RT=-2*math.sqrt(Cm**7/(Cm**7+25**7))*math.sin(math.radians(60)*math.exp(-((Hm-math.radians(275))**2)/(math.radians(25)**2)))
    return math.sqrt(DL**2 + (DC/(1+0.045*Cm))**2 + (DH/(1+0.015*Cm))**2 + RT*DC*DH)

def calculate_differences(df, L,A,B):
    return [round(ciede2000(L,A,B, r['L'],r['a*'],r['b*']),4) for _,r in df.iterrows()]

@app.route('/', methods=['GET','POST'])
def upload_and_process():
    graph_2d = graph_3d = None
    filt_cols = filt_data = None
    full_cols = full_data = None

    sheets = session.get('sheet_names')
    fp     = session.get('file_path')
    sel    = session.get('selected_sheet')
    L=A=B = 0.0

    # 기본 임계값
    L_thr, C_thr, h_thr, dE_thr = 1.0, 1.5, 3.0, 2.5

    if request.method=='POST':
        # 1) 파일 업로드
        if 'file' in request.files and request.files['file'].filename:
            f=request.files['file']
            ext=f.filename.rsplit('.',1)[-1]
            name=f"{uuid.uuid4()}.{ext}"
            path=os.path.join(UPLOAD_FOLDER,name)
            f.save(path)
            xls=pd.ExcelFile(path)
            session['sheet_names']=xls.sheet_names
            session['file_path']=path
            session['selected_sheet']=None
            return redirect(url_for('upload_and_process'))

        # 업로드 안 된 상태면 빈화면
        if not fp or not sheets:
            return render_template('index.html')

        # 2) 시트 선택 유지/설정
        form_s = request.form.get('sheet')
        if form_s:
            sel = form_s
            session['selected_sheet']=sel
        elif not sel:
            sel=sheets[0]
            session['selected_sheet']=sel

        # 3) threshold 입력 처리
        try:
            L_thr  = float(request.form.get('L_thr')  or L_thr)
            C_thr  = float(request.form.get('C_thr')  or C_thr)
            h_thr  = float(request.form.get('h_thr')  or h_thr)
            dE_thr = float(request.form.get('dE_thr') or dE_thr)
        except ValueError:
            return "임계값은 숫자로 입력하세요."

        # 4) L,a*,b* 입력 처리
        vals = request.form.get('input_values')
        act  = request.form.get('action')
        xls  = pd.ExcelFile(fp)
        df   = xls.parse(sel)
        df.columns = df.columns.map(str).str.strip()

        # 필수 컬럼 확보
        for c in ['L','a*','b*','sR','sG','sB','HEX']:
            if c not in df: df[c] = '' if c=='HEX' else 0

        # 입력값 결정
        if act=="시트 값으로 그래프 보기":
            L,A,B = df['L'].mean(), df['a*'].mean(), df['b*'].mean()
        elif act=="입력값 위치 확인" and vals:
            try:
                L,A,B = map(float, vals.split(','))
            except:
                return "L,a*,b* 형식 오류"
        else:
            L,A,B = df['L'].mean(), df['a*'].mean(), df['b*'].mean()

        # 입력값 행 추가
        m=(df['L']==L)&(df['a*']==A)&(df['b*']==B)
        if not m.any():
            new={col:'' for col in df.columns}
            new.update({'L':L,'a*':A,'b*':B})
            df=pd.concat([df, pd.DataFrame([new])], ignore_index=True)

        # dE, C, h, ITA 계산
        df['dE'] = calculate_differences(df, L, A, B)
        df['C']  = (df['a*']**2 + df['b*']**2)**0.5
        df['h']  = df.apply(lambda r: math.degrees(math.atan2(r['b*'], r['a*'])), axis=1)
        df['ITA']= df.apply(lambda r: math.degrees(math.atan((r['L']-50)/r['b*'])) if r['b*']!=0 else 0, axis=1)

        # ① 입력값 기준 C, h 계산 (L, A, B 사용)
        input_C = math.sqrt(A**2 + B**2)
        input_h = math.degrees(math.atan2(B, A)) % 360
        
        # ② full: 정렬된 전체 DataFrame
        full = df.sort_values('dE').reset_index(drop=True)
        full_cols = full.columns.tolist()
        full_data = full.to_dict('records')

        # 5) ≤ threshold 필터링 (L, A, B 일관 적용)
        mask = (
            (full['dE'] <= dE_thr) &
            (full['L'].sub(L).abs()     <= L_thr) &
            (full['C'].sub(input_C).abs() <= C_thr) &
            (full['h'].sub(input_h).abs() <= h_thr)
        )         
        filt = full[mask]

        # 필터링 결과 없으면 최소 입력값 행만 사용
        input_mask = (full['L'] == L) & (full['a*'] == A) & (full['b*'] == B)
        # 필터 결과가 비어 있으면 입력값만
        if filt.empty:
            filt = full[input_mask]

        filt_cols = filt.columns.tolist()
        filt_data = filt.to_dict('records')

        # 6) 2D scatter (h vs ITA)
        fig2 = px.scatter(
            filt,
            x='h', y='ITA',
            range_x=[30,90], range_y=[-90,90],
            title="Filtered h vs ITA (including input)"
        )
        graph_2d = fig2.to_html(full_html=False, include_plotlyjs='cdn')

        # 7) 3D 전체 scatter
        cols3 = [
            'blue' if (r['L']==L and r['a*']==A and r['b*']==B)
            else f"rgb({r['sR']},{r['sG']},{r['sB']})"
            for r in full_data
        ]
        fig3 = go.Figure(data=[go.Scatter3d(
            x=full['a*'], y=full['b*'], z=full['L'],
            mode='markers', marker=dict(size=3.5, opacity=0.7, color=cols3)
        )])
        fig3.update_layout(title="3D Color Scatter", width=600, height=600)
        graph_3d = fig3.to_html(full_html=False, include_plotlyjs='cdn')

    return render_template('index.html',
        sheet_names=sheets, selected_sheet=sel,
        graph_2d=graph_2d, filt_cols=filt_cols, filt_data=filt_data,
        graph_3d=graph_3d, full_cols=full_cols, full_data=full_data,
        L_thr=L_thr, C_thr=C_thr, h_thr=h_thr, dE_thr=dE_thr
    )

if __name__=='__main__':
    app.run(debug=True)
