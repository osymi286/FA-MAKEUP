from flask import Flask, request, render_template
import pandas as pd

app = Flask(__name__)

# 엑셀 파일 읽어오기
all_sheets = pd.read_excel('★쿠션,파운데이션 측색데이터 색차계산(20250514)_dE0_GRAPH.xlsm', sheet_name=None, engine='openpyxl')

# 시트 이름 목록 가져오기
sheet_names = list(all_sheets.keys())  # Ensure it's a list

@app.route('/', methods=['GET', 'POST'])
def index():
    print(sheet_names)
    selected_sheet_name = None
    data = ""
    message = ""

    if request.method == 'POST':
        selected_sheet_name = request.form.get('sheet_name')
        if selected_sheet_name in all_sheets:
            selected_df = all_sheets[selected_sheet_name]
            data = selected_df.to_html()  # Convert DataFrame to HTML
            message = f"Data from the sheet '{selected_sheet_name}' is loaded."
        else:
            message = f"Sheet '{selected_sheet_name}' not found or is hidden."

    return render_template('index.html', sheet_names=sheet_names, message=message, data=data)

if __name__ == '__main__':
    app.run(debug=True)