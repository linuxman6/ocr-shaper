import json
import os
import glob
import sys
import subprocess
import re

# --- tkinterdnd2の自動セットアップ ---
try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
except ImportError:
    print("必要なライブラリ 'tkinterdnd2' をインストールしています...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "tkinterdnd2"])
        from tkinterdnd2 import TkinterDnD, DND_FILES
    except Exception as e:
        print(f"インストールの自動実行に失敗しました。手動で 'pip install tkinterdnd2' を実行してください。\nエラー: {e}")
        sys.exit(1)

import tkinter as tk
from tkinter import messagebox
from tkinter import ttk

def clean_vertical_text(text):
    """縦書きOCR特有の誤認識やノイズを修正するフィルター"""
    if not text:
        return ""
    text = text.replace(" ", "").replace("　", "")
    text = re.sub(r'(?<=[ァ-ヶー一-龠])[丨｜\|](?=[ァ-ヶー一-龠]|$)', 'ー', text)
    return text

def process_ndlocr_json(target_folder, output_name):
    """単一フォルダのJSONを処理するコアロジック"""
    json_files = sorted(glob.glob(os.path.join(target_folder, "*.json")))
    
    if not json_files:
        return False, "JSONファイルが見つかりません。"

    full_text_blocks = []
    current_paragraph = ""

    # 文末と判定する記号
    sentence_endings = (
        '。', '！', '？', '!', '?', 
        '」', '』', '】', '）', '〕', '〉', '》', '］', '＞',
        '㳃', '㴴', '㵵', 'ゝ', 'ゞ', '々'
    )

    # 🎯 行頭の全角スペース挿入をパス（スキップ）したい記号のリスト
    skip_indent_chars = (
        '「', '『', '（', '(',  # 鉤括弧、二重鉤括弧、全角・半角丸括弧
        '【', '〔', '［', '[',  # その他の一般的な括弧類
        '〈', '《'
    )

    for file_path in json_files:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            contents = data.get("contents", [])
            for page in contents:
                lines = page.get("lines", []) if isinstance(page, dict) else page
                if not isinstance(lines, list):
                    continue

                for line_data in lines:
                    if not isinstance(line_data, dict):
                        continue
                        
                    text = line_data.get("text", "").strip()
                    if not text:
                        continue
                    
                    if re.match(r'^[0-9０-９]+$', text):
                        continue

                    text = clean_vertical_text(text)
                    if not text:
                        continue

                    current_paragraph += text
                    
                    if text.endswith(sentence_endings):
                        # 🎯 修正1: 既にスペースがあるか、指定の記号で始まる場合はスペースを入れない
                        if not current_paragraph.startswith('　') and not current_paragraph.startswith(skip_indent_chars):
                            current_paragraph = '　' + current_paragraph
                        full_text_blocks.append(current_paragraph)
                        current_paragraph = ""

        except Exception as e:
            return False, f"エラー発生 ({os.path.basename(file_path)}): {str(e)}"

    if current_paragraph:
        # 🎯 修正2: ループ外の残りテキストに対しても同様の判定を行う
        if not current_paragraph.startswith('　') and not current_paragraph.startswith(skip_indent_chars):
            current_paragraph = '　' + current_paragraph
        full_text_blocks.append(current_paragraph)

    output_path = os.path.normpath(os.path.join(target_folder, output_name))
    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write("\n".join(full_text_blocks))
        return True, "成功"
    except Exception as e:
        return False, f"保存エラー: {str(e)}"


# --- GUIクラスの定義 ---
class OcrBatchCombinerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("NDLOCR-Lite 自動ファイル名一括結合ツール")
        self.root.geometry("550x320") # 入力欄を減らしたため高さを調整
        self.root.resizable(False, False)
        
        self.style = ttk.Style()
        self.style.theme_use('vista')

        main_frame = ttk.Frame(root, padding="20")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # 説明ラベル
        desc_label = ttk.Label(
            main_frame, 
            text="JSONが含まれるフォルダをまとめて選択し、ドラッグ＆ドロップしてください。\n"
                 "※出力ファイル名は「フォルダ名.txt」として各フォルダ内に自動作成されます。", 
            justify="left"
        )
        desc_label.pack(anchor=tk.W, pady=(0, 10))

        # 🎯 ドラッグ＆ドロップ専用エリア
        self.drop_target = tk.Label(
            main_frame, 
            text="【ここに複数のフォルダをドロップ】", 
            bg="#f0f0f0", 
            fg="#555555",
            relief="groove", 
            bd=2, 
            height=5
        )
        self.drop_target.pack(fill=tk.X, pady=10)
        
        # D&Dイベントの登録
        self.drop_target.drop_target_register(DND_FILES)
        self.drop_target.dnd_bind('<<Drop>>', self.handle_drop)

        # 選択されたフォルダのリスト保持用
        self.selected_folders = []

        # 状態表示用ラベル
        self.status_label = ttk.Label(main_frame, text="待機中...", foreground="#666666")
        self.status_label.pack(anchor=tk.W, pady=(10, 0))

        # 実行ボタン
        self.run_btn = ttk.Button(main_frame, text="一括処理を実行する", command=self.run_batch_process)
        self.run_btn.pack(fill=tk.X, pady=(5, 0))

    def handle_drop(self, event):
        parsed_paths = self.root.tk.splitlist(event.data)
        if not parsed_paths:
            return
            
        self.selected_folders = []
        for p in parsed_paths:
            path = os.path.normpath(p)
            # ファイルが直接ドロップされた場合は、その親フォルダを対象にする
            if os.path.isfile(path):
                path = os.path.dirname(path)
            
            if os.path.exists(path) and path not in self.selected_folders:
                self.selected_folders.append(path)
        
        if self.selected_folders:
            count = len(self.selected_folders)
            self.drop_target.config(bg="#e1f5fe", text=f"【確認】{count} 件のフォルダが選択されています")
            self.status_label.config(text=f"処理対象: {count} 個のフォルダ。ボタンを押すと開始します。")

    def run_batch_process(self):
        if not self.selected_folders:
            messagebox.showerror("エラー", "処理するフォルダをドロップしてください。")
            return

        self.run_btn.config(state=tk.DISABLED)
        
        success_count = 0
        failed_folders = []

        # 複数フォルダを順次ループ処理
        for idx, folder in enumerate(self.selected_folders, 1):
            folder_name = os.path.basename(folder)
            
            # 🎯 フォルダ名をそのままファイル名として採用
            outfile = f"{folder_name}.txt"
            
            self.status_label.config(text=f"処理中 ({idx}/{len(self.selected_folders)}): {folder_name} -> {outfile}")
            self.root.update()

            success, msg = process_ndlocr_json(folder, outfile)
            if success:
                success_count += 1
            else:
                failed_folders.append(f"{folder_name} ({msg})")

        # 処理完了後のUIリセットと通知
        self.run_btn.config(state=tk.NORMAL)
        self.status_label.config(text="すべての処理が終了しました。")
        
        result_msg = f"一括処理が完了しました！\n\n成功: {success_count} 件"
        if failed_folders:
            result_msg += f"\n失敗: {len(failed_folders)} 件\n\n【失敗詳細】\n" + "\n".join(failed_folders)
            messagebox.showwarning("処理完了（一部失敗あり）", result_msg)
        else:
            messagebox.showinfo("完了", result_msg)
            
        # 次のドロップのためにリセット
        self.selected_folders = []
        self.drop_target.config(bg="#f0f0f0", text="【ここに複数のフォルダをドロップ】")

if __name__ == "__main__":
    root = TkinterDnD.Tk()
    app = OcrBatchCombinerApp(root)
    root.mainloop()
