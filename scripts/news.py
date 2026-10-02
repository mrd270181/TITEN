#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Kumpulkan berita sentimen pasar & emiten + kurs USD/IDR untuk menu NEWS TITEN.

Dijalankan otomatis oleh GitHub Actions (.github/workflows/news.yml), bisa juga
manual:  python scripts/news.py
Hasil: data/news.json  (berita 7 hari terakhir + kurs terbaru & 30 hari)

Sumber berita : Google Berita RSS (judul + tautan saja, isi tetap di situs asli).
Sumber kurs   : Yahoo Finance (IDR=X), cadangan open.er-api.com.
Hanya pustaka bawaan Python - tidak perlu pip install.
"""
import json, os, re, time, html, datetime, email.utils
import urllib.request, urllib.parse
import xml.etree.ElementTree as ET

AKAR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(AKAR, 'data')
KELUAR = os.path.join(DATA, 'news.json')
SIMPAN_HARI = 7
MAKS_ITEM = 800
UA = 'Mozilla/5.0 (compatible; TITEN-news/1.0)'

# kata kunci pencarian sentimen PASAR (Google Berita, 2 hari terakhir)
Q_PASAR = ['IHSG', '"Bursa Efek Indonesia"', 'saham "net sell" asing', 'saham "net buy" asing',
           'rupiah dolar hari ini', '"BI Rate"', '"The Fed" suku bunga', 'MSCI Indonesia saham',
           'IHSG sesi', 'pasar saham Indonesia hari ini']

# kata penanda sentimen di JUDUL (huruf kecil). Kasar tapi cepat.
POSITIF = ['naik', 'menguat', 'melonjak', 'melesat', 'meroket', 'terbang', 'rebound', 'reli', 'rally',
           'laba', 'untung', 'cuan', 'dividen', 'buyback', 'akuisisi', 'ekspansi', 'rekor', 'tertinggi',
           'positif', 'net buy', 'borong', 'diborong', 'kontrak baru', 'tumbuh', 'optimis', 'hijau',
           'ara ', 'auto reject atas', 'upgrade', 'surplus', 'lampaui']
NEGATIF = ['turun', 'melemah', 'anjlok', 'ambruk', 'ambles', 'amblas', 'merosot', 'terkoreksi', 'koreksi',
           'rugi', 'merugi', 'gagal bayar', 'pkpu', 'pailit', 'suspensi', 'disuspensi', 'suspend',
           'delisting', 'net sell', 'dilepas', 'lepas', 'negatif', 'tertekan', 'merah', 'longsor',
           'terjun', 'waspada', 'gugatan', 'sanksi', 'arb', 'auto reject bawah', 'downgrade', 'defisit',
           'terendah', 'jatuh', 'kabur', 'outflow', 'boncos']
# kode emiten yang juga kata umum - hanya dihitung kalau didahului kata "saham"
KODE_UMUM = {'DATA', 'BANK', 'GOOD', 'CASH', 'LIFE', 'HOME', 'FOOD', 'GOLD', 'TECH', 'KING',
             'BEST', 'MAIN', 'FAST', 'SAFE', 'TRUE', 'CITY', 'LAND', 'ASIA', 'INDO', 'JAVA', 'BALI',
             'NUSA', 'JAYA', 'DEAL', 'CARE', 'HOPE', 'PURE', 'RICH', 'NICE', 'ZONE', 'IDEA', 'FIRE'}
BUANG_NAMA = re.compile(r'\b(pt|tbk|persero|\(persero\)|indonesia|international|internasional)\b\.?', re.I)


def ambil(url, timeout=25):
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def baca_json(nama, bawaan):
    try:
        with open(os.path.join(DATA, nama), encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return bawaan


def daftar_emiten():
    """kode -> nama inti (tanpa PT/Tbk), dari awal-lk.json (semua emiten bursa)."""
    nama = (baca_json('awal-lk.json', {}) or {}).get('nama') or {}
    hasil = {}
    for k, n in nama.items():
        inti = BUANG_NAMA.sub('', n or '')
        inti = re.sub(r'[().,]', ' ', inti)
        inti = re.sub(r'\s+', ' ', inti).strip()
        hasil[k] = inti if len(inti) >= 8 and len(inti.split()) >= 2 else ''
    return hasil


def kode_dicari():
    """emiten yang dicari beritanya satu per satu: emiten data broker + watchlist bawaan."""
    k = baca_json('kamus.json', {}) or {}
    a = baca_json('awal-lk.json', {}) or {}
    kode = list(k.get('emiten') or [])
    kode += [w.get('k') for w in (a.get('watch') or []) if w.get('k')]
    return sorted(set(kode))


def rss(q):
    url = ('https://news.google.com/rss/search?q=' + urllib.parse.quote(q) +
           '&hl=id&gl=ID&ceid=ID:id')
    root = ET.fromstring(ambil(url))
    hasil = []
    for it in root.iter('item'):
        judul = html.unescape(it.findtext('title') or '').strip()
        sumber_el = it.find('source')
        sumber = (sumber_el.text or '').strip() if sumber_el is not None else ''
        if sumber and judul.endswith(' - ' + sumber):
            judul = judul[: -len(' - ' + sumber)].strip()
        try:
            w = int(email.utils.parsedate_to_datetime(it.findtext('pubDate')).timestamp())
        except Exception:
            continue
        hasil.append({'t': judul, 's': sumber, 'u': it.findtext('link') or '', 'w': w})
    return hasil


def cari_emiten(judul, emiten):
    ketemu = set()
    for m in re.finditer(r'\b[A-Z]{4}\b', judul):
        k = m.group(0)
        if k not in emiten:
            continue
        if k in KODE_UMUM and not re.search(r'saham\s+(?:\w+\s+)?' + k + r'\b', judul, re.I):
            continue
        ketemu.add(k)
    low = judul.lower()
    for k, inti in emiten.items():
        if inti and inti.lower() in low:
            ketemu.add(k)
    return sorted(ketemu)


def skor(judul):
    t = ' ' + judul.lower() + ' '
    p = sum(1 for x in POSITIF if re.search(r'\b' + re.escape(x.strip()) + r'\b', t))
    n = sum(1 for x in NEGATIF if re.search(r'\b' + re.escape(x.strip()) + r'\b', t))
    return p - n


def kunci(judul):
    return re.sub(r'[^a-z0-9]', '', judul.lower())[:90]


def kurs():
    try:
        d = json.loads(ambil('https://query1.finance.yahoo.com/v8/finance/chart/IDR=X?range=1mo&interval=1d'))
        r = d['chart']['result'][0]
        meta = r['meta']
        tgl = [datetime.datetime.utcfromtimestamp(t).strftime('%Y-%m-%d') for t in r['timestamp']]
        cl = r['indicators']['quote'][0]['close']
        riw = [[t, round(c, 1)] for t, c in zip(tgl, cl) if c]
        harga = meta.get('regularMarketPrice') or (riw[-1][1] if riw else None)
        sebelum = None
        if len(riw) >= 2:
            sebelum = riw[-2][1] if riw[-1][0] == datetime.datetime.utcfromtimestamp(
                meta.get('regularMarketTime', 0)).strftime('%Y-%m-%d') else riw[-1][1]
        return {'harga': round(harga, 1), 'sebelum': sebelum, 'waktu': meta.get('regularMarketTime'),
                'riwayat': riw, 'sumber': 'Yahoo Finance'}
    except Exception as e:
        print('  kurs Yahoo gagal:', e)
    try:
        d = json.loads(ambil('https://open.er-api.com/v6/latest/USD'))
        return {'harga': round(d['rates']['IDR'], 1), 'sebelum': None,
                'waktu': d.get('time_last_update_unix'), 'riwayat': [], 'sumber': 'open.er-api.com'}
    except Exception as e:
        print('  kurs cadangan gagal:', e)
    return None


def main():
    lama = baca_json('news.json', {}) or {}
    emiten = daftar_emiten()
    batas = int(time.time()) - SIMPAN_HARI * 86400
    item = {kunci(x['t']): x for x in (lama.get('item') or []) if x.get('w', 0) >= batas}
    baru = 0

    def masukkan(x, pasar):
        nonlocal baru
        if x['w'] < batas or not x['t']:
            return False
        e = cari_emiten(x['t'], emiten)
        if not pasar and not e:
            return False
        k = kunci(x['t'])
        ada = item.get(k)
        if ada:
            ada['k'] = ''.join(sorted(set(ada.get('k', '')) | ({'p'} if pasar else set()) | ({'e'} if e else set())))
            ada['e'] = sorted(set(ada.get('e') or []) | set(e))
            return True
        item[k] = {'t': x['t'], 's': x['s'], 'u': x['u'], 'w': x['w'], 'e': e,
                   'k': ('p' if pasar else '') + ('e' if e else ''), 'n': skor(x['t'])}
        baru += 1
        return True

    gagal = 0
    for q in Q_PASAR:
        try:
            for x in rss(q + ' when:2d'):
                masukkan(x, True)
        except Exception as ex:
            gagal += 1
            print('  gagal', q, ex)
        time.sleep(1.2)
    kode = kode_dicari()
    for i in range(0, len(kode), 8):
        q = ' OR '.join('"saham %s"' % k for k in kode[i:i + 8]) + ' when:3d'
        try:
            for x in rss(q):
                masukkan(x, False)
        except Exception as ex:
            gagal += 1
            print('  gagal', kode[i:i + 8], ex)
        time.sleep(1.2)

    daftar = sorted(item.values(), key=lambda x: -x['w'])[:MAKS_ITEM]
    k = kurs() or lama.get('kurs')
    hasil = {'dibuat': int(time.time()), 'kurs': k, 'item': daftar}
    with open(KELUAR, 'w', encoding='utf-8') as f:
        json.dump(hasil, f, ensure_ascii=False, separators=(',', ':'))
    print('berita: %d (baru %d), permintaan gagal: %d, kurs: %s'
          % (len(daftar), baru, gagal, k and k.get('harga')))


if __name__ == '__main__':
    main()
