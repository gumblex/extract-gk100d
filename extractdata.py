#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import io
import sys
import zlib
import struct
import shutil
import itertools
import mimetypes
import collections

xor = lambda t, k: bytes(x^y for x,y in zip(t, itertools.cycle(k)))

def assert_string(infile, value):
    assert infile.read(len(value)) == value


class AttrDict(dict):
    def __init__(self, *args, **kwargs):
        super(AttrDict, self).__init__(*args, **kwargs)
        self.__dict__ = self


SegmChunk = collections.namedtuple('SegmChunk', 'flags offset size size_comp')

MAGICS = (
('ogg', b'\x4f\x67\x67\x53', b'\x00\x02\x00\x00\x00\x00\x00\x00'),
('wmv', b'\x30\x26\xB2\x75', b'\x8E\x66\xCF\x11\xA6\xD9\x00\xAA'),
('tjs', b'\xFF\xFE\x76\x00', b'\x61\x00\x72\x00\x20\x00\x61\x00'),
)

class Xp3File:
    MAGIC = b'XP3\r\n\x20\x0A\x1A\x8B\x67\x01'
    KEYHEAD = b'\x0c\xf0\x04a\x00JB\x00'

    def __init__(self, filename):
        self.filename = filename
        self.fp = open(self.filename, 'rb')
        self.table = []
        assert_string(self.fp, self.MAGIC)
        self.fp.seek(19)
        self.version = 2 if self._read_int(4) == 1 else 1
        self.fp.seek(len(self.MAGIC))
        if self.version == 2:
            self.additional_header_offset = self._read_int(8)
            self.minor_version = self._read_int(4)
            assert self.minor_version == 1
            self.fp.seek(self.additional_header_offset)
            # 80
            self.flags = self._read_int(1)
            # 00 00 00 00 00 00 00 00
            self.fp.read(8)
            self.table_offset = self._read_int(8)
        else:
            self.table_offset = self._read_int(8)
        self.read_table()

    def read_table(self):
        self.fp.seek(self.table_offset)
        self.table_compressed = self._read_int(1)
        self.table_size_comp = self._read_int(8)
        if self.table_compressed:
            self.table_size_orig = self._read_int(8)
        else:
            self.table_size_orig = self.table_size_comp
        table_data = self.fp.read(self.table_size_comp)
        if self.table_compressed:
            table_data = zlib.decompress(table_data)
        self.table_raw = table_data
        stream = io.BytesIO(table_data)
        while 1:
            magic = stream.read(4)
            if not magic:
                break
            assert magic == b'File'
            d = AttrDict()
            d.length = self._read_int(8, stream)
            assert_string(stream, b'info')
            d.info_length = self._read_int(8, stream)
            d.flags = self._read_int(4, stream)
            d.size = self._read_int(8, stream)
            d.size_comp = self._read_int(8, stream)
            offset = stream.tell()
            # should be name
            name_length = self._read_int(2, stream)
            if d.info_length == 22 + name_length*2:
                d.name = stream.read(name_length*2).decode('utf-16-le', 'ignore')
                d.name_good = True
            else:
                stream.seek(offset)
                d.name = stream.read(12)
                d.name_good = False
            assert_string(stream, b'segm')
            d.segm_number = self._read_int(8, stream) // 28
            d.segm = []
            for i in range(d.segm_number):
                d.segm.append(SegmChunk(
                    self._read_int(4, stream),
                    self._read_int(8, stream),
                    self._read_int(8, stream),
                    self._read_int(8, stream)
                ))
            assert_string(stream, b'adlr')
            # length
            self._read_int(8, stream)
            d.adlr = stream.read(4)
            self.table.append(d)

    def get(self, num, decrypt=True):
        fileinfo = self.table[num]
        outbuffer = io.BytesIO()
        for segm in fileinfo.segm:
            self.fp.seek(segm.offset)
            data = self.fp.read(segm.size_comp)
            if segm.flags & 7: # compressed
                data = zlib.decompress(data)
            if decrypt:
                data = self.decrypt(fileinfo, data)
            assert len(data) == segm.size
            outbuffer.write(data)
        outbuffer.seek(0)
        return outbuffer

    def extract(self, out):
        for k, fileinfo in enumerate(self.table, 1):
            outbuffer = self.get(k-1)
            if fileinfo.name_good:
                filename = fileinfo.name
                if len(filename.encode('utf-8')) > 128:
                    fn, ext = os.path.splitext(filename)
                    filename = fn[:64] + ext
            else:
                ext = self.detect_ext(outbuffer.read(1024))
                filename = ('%04d' % k) + (ext or '.txt')
            outbuffer.seek(0)
            dirname = os.path.dirname(filename)
            os.makedirs(os.path.join(out, dirname), exist_ok=True)
            with open(os.path.join(out, filename), 'wb') as f:
                shutil.copyfileobj(outbuffer, f)
            print('Extracted %s' % filename)

    def detect_ext(self, data):
        import magic
        fmagic = magic.detect_from_content(data)
        if fmagic.mime_type.startswith('text/'):
            if fmagic.encoding == 'unknown-8bit':
                ext = '.bin'
            else:
                text = data.decode(fmagic.encoding)
                if '@return' in text or '*start' in text or '.ks' in text or '[w]' in text:
                    ext = '.ks'
                elif '.tjs' in text or '%[' in text or '];' in text:
                    ext = '.tjs'
                else:
                    ext = '.txt'
        else:
            ext = mimetypes.guess_extension(fmagic.mime_type)
            if ext == '.jpeg':
                ext = '.jpg'
            elif ext == '.oga':
                ext = '.ogg'
            elif ext == '.asf':
                ext = '.wmv'
        return ext

    def _read_int(self, size, infile=None, endian='<', signed=False):
        inttypes = {1: 'B', 2: 'H', 4: 'I', 8: 'Q'}
        d = (infile or self.fp).read(size)
        if signed:
            return struct.unpack(endian + inttypes[size].lower(), d)[0]
        else:
            return struct.unpack(endian + inttypes[size], d)[0]

    def decrypt(self, fileinfo, data):
        return data

    def close(self):
        self.fp.close()

    def __del__(self):
        self.fp.close()

class EncryptedXp3File(Xp3File):

    def load_key(self):
        if hasattr(self, 'keyhead'):
            return
        # Gaokao Love 100 Days Disc Ver.
        elif self.table_offset == 1631288384:
            self.keyhead = b'\x0c\xf0\x04a\x00JB\x00'
        else:
            self.keyhead = b'\x1d\xef[\xa3\x00\xcaA\x00'

    def detect_key(self):
        for k, fileinfo in enumerate(self.table):
            segm = fileinfo.segm[0]
            self.fp.seek(segm.offset)
            if segm.flags & 7: # compressed
                data = self.fp.read(segm.size_comp)
                data = zlib.decompress(data)[:12]
            else:
                data = self.fp.read(12)
            for ftype, head1, head2 in MAGICS:
                if xor(head1, fileinfo.adlr) == data[:4]:
                    self.keyhead = xor(head2, data[4:])
                    return self.keyhead

    def decrypt(self, fileinfo, data):
        self.load_key()
        return xor(data, fileinfo.adlr + self.keyhead)


def main():
    args = sys.argv[1:]
    encrypted = False
    if args[0] == '-e':
        encrypted = True
        args.pop(0)
        xp3file = EncryptedXp3File(args[0])
    else:
        xp3file = Xp3File(args[0])
    print('File loaded.')
    xp3file.extract(args[1])

if __name__ == '__main__':
    main()
