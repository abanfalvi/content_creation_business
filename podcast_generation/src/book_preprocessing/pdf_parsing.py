"""PDF -> Markdown via the MinerU API."""
import io
import os
import zipfile

import requests
from dotenv import load_dotenv

load_dotenv()


# It currently produces a url for zip file
def parse_pdf(filepath: str, book_name: str, page_ranges: str) -> str | None:
    token = os.getenv("MINERU_API_KEY", "")
    url = "https://mineru.net/api/v4/file-urls/batch"
    header = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
    }
    data = {
        "files": [{"name": filepath, "data_id": book_name, "page_ranges": page_ranges, "is_ocr": True,}],
        "model_version": "vlm",
        "language": "en"
    }
    file_path = [filepath]

    try:
        response = requests.post(url,headers=header,json=data)
        if response.status_code == 200:
            result = response.json()
            print('response success. result:{}'.format(result))
            if result["code"] == 0:
                batch_id = result["data"]["batch_id"]
                urls = result["data"]["file_urls"]
                print('batch_id:{},urls:{}'.format(batch_id, urls))
                for i in range(0, len(urls)):
                    with open(file_path[i], 'rb') as f:
                        requests.put(urls[i], data=f)
                    poll_url = f"https://mineru.net/api/v4/extract-results/batch/{batch_id}"
                    while True:
                        result = requests.get(poll_url, headers=header).json()
                        file_result = result["data"]["extract_result"][0]
                        if file_result["state"] == "done":
                            return file_result["full_zip_url"]
                        if file_result["state"] == "failed":
                            raise RuntimeError(file_result.get("err_msg"))
                        # time.sleep(3)
            else:
                print('apply upload url failed,reason:{}'.format(result["msg"]))
        else:
            print('response not success. status:{} ,result:{}'.format(response.status_code, response))
    except Exception as err:
        print(err)


def save_markdown(zip_url: str, output_path: str, append: bool = False):
    res = requests.get(zip_url)
    with zipfile.ZipFile(io.BytesIO(res.content)) as zf:
        md_name = next(n for n in zf.namelist() if n.endswith(".md"))
        mode = "ab" if append and os.path.exists(output_path) else "wb"
        with zf.open(md_name) as f, open(output_path, mode) as out:
            out.write(f.read())
