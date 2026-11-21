/*
 * tgnative: compiled crypto for RetroTele (Python for S60 1.4.5 = Python 2.2).
 *
 *   ige_encrypt(data, key32, iv32) -> str     AES-256-IGE
 *   ige_decrypt(data, key32, iv32) -> str
 *   sha1(data) -> 20 bytes
 *   sha256(data) -> 32 bytes
 *   pbkdf2_sha512(password, salt, iterations) -> 64 bytes
 *
 * Plain C with only constant tables (Symbian DLLs should have no writable
 * static data). The same file builds as a desktop Python 2.7 extension for
 * the PC tests (tests/test_native.py).
 */
#include "Python.h"
#include <string.h>

typedef unsigned char u8;
typedef unsigned int u32;
typedef unsigned long long u64;

/* ------------------------------------------------------------------ AES */

static const u8 SBOX[256] = {
0x63,0x7c,0x77,0x7b,0xf2,0x6b,0x6f,0xc5,0x30,0x01,0x67,0x2b,0xfe,0xd7,0xab,0x76,
0xca,0x82,0xc9,0x7d,0xfa,0x59,0x47,0xf0,0xad,0xd4,0xa2,0xaf,0x9c,0xa4,0x72,0xc0,
0xb7,0xfd,0x93,0x26,0x36,0x3f,0xf7,0xcc,0x34,0xa5,0xe5,0xf1,0x71,0xd8,0x31,0x15,
0x04,0xc7,0x23,0xc3,0x18,0x96,0x05,0x9a,0x07,0x12,0x80,0xe2,0xeb,0x27,0xb2,0x75,
0x09,0x83,0x2c,0x1a,0x1b,0x6e,0x5a,0xa0,0x52,0x3b,0xd6,0xb3,0x29,0xe3,0x2f,0x84,
0x53,0xd1,0x00,0xed,0x20,0xfc,0xb1,0x5b,0x6a,0xcb,0xbe,0x39,0x4a,0x4c,0x58,0xcf,
0xd0,0xef,0xaa,0xfb,0x43,0x4d,0x33,0x85,0x45,0xf9,0x02,0x7f,0x50,0x3c,0x9f,0xa8,
0x51,0xa3,0x40,0x8f,0x92,0x9d,0x38,0xf5,0xbc,0xb6,0xda,0x21,0x10,0xff,0xf3,0xd2,
0xcd,0x0c,0x13,0xec,0x5f,0x97,0x44,0x17,0xc4,0xa7,0x7e,0x3d,0x64,0x5d,0x19,0x73,
0x60,0x81,0x4f,0xdc,0x22,0x2a,0x90,0x88,0x46,0xee,0xb8,0x14,0xde,0x5e,0x0b,0xdb,
0xe0,0x32,0x3a,0x0a,0x49,0x06,0x24,0x5c,0xc2,0xd3,0xac,0x62,0x91,0x95,0xe4,0x79,
0xe7,0xc8,0x37,0x6d,0x8d,0xd5,0x4e,0xa9,0x6c,0x56,0xf4,0xea,0x65,0x7a,0xae,0x08,
0xba,0x78,0x25,0x2e,0x1c,0xa6,0xb4,0xc6,0xe8,0xdd,0x74,0x1f,0x4b,0xbd,0x8b,0x8a,
0x70,0x3e,0xb5,0x66,0x48,0x03,0xf6,0x0e,0x61,0x35,0x57,0xb9,0x86,0xc1,0x1d,0x9e,
0xe1,0xf8,0x98,0x11,0x69,0xd9,0x8e,0x94,0x9b,0x1e,0x87,0xe9,0xce,0x55,0x28,0xdf,
0x8c,0xa1,0x89,0x0d,0xbf,0xe6,0x42,0x68,0x41,0x99,0x2d,0x0f,0xb0,0x54,0xbb,0x16};

static const u8 RSBOX[256] = {
0x52,0x09,0x6a,0xd5,0x30,0x36,0xa5,0x38,0xbf,0x40,0xa3,0x9e,0x81,0xf3,0xd7,0xfb,
0x7c,0xe3,0x39,0x82,0x9b,0x2f,0xff,0x87,0x34,0x8e,0x43,0x44,0xc4,0xde,0xe9,0xcb,
0x54,0x7b,0x94,0x32,0xa6,0xc2,0x23,0x3d,0xee,0x4c,0x95,0x0b,0x42,0xfa,0xc3,0x4e,
0x08,0x2e,0xa1,0x66,0x28,0xd9,0x24,0xb2,0x76,0x5b,0xa2,0x49,0x6d,0x8b,0xd1,0x25,
0x72,0xf8,0xf6,0x64,0x86,0x68,0x98,0x16,0xd4,0xa4,0x5c,0xcc,0x5d,0x65,0xb6,0x92,
0x6c,0x70,0x48,0x50,0xfd,0xed,0xb9,0xda,0x5e,0x15,0x46,0x57,0xa7,0x8d,0x9d,0x84,
0x90,0xd8,0xab,0x00,0x8c,0xbc,0xd3,0x0a,0xf7,0xe4,0x58,0x05,0xb8,0xb3,0x45,0x06,
0xd0,0x2c,0x1e,0x8f,0xca,0x3f,0x0f,0x02,0xc1,0xaf,0xbd,0x03,0x01,0x13,0x8a,0x6b,
0x3a,0x91,0x11,0x41,0x4f,0x67,0xdc,0xea,0x97,0xf2,0xcf,0xce,0xf0,0xb4,0xe6,0x73,
0x96,0xac,0x74,0x22,0xe7,0xad,0x35,0x85,0xe2,0xf9,0x37,0xe8,0x1c,0x75,0xdf,0x6e,
0x47,0xf1,0x1a,0x71,0x1d,0x29,0xc5,0x89,0x6f,0xb7,0x62,0x0e,0xaa,0x18,0xbe,0x1b,
0xfc,0x56,0x3e,0x4b,0xc6,0xd2,0x79,0x20,0x9a,0xdb,0xc0,0xfe,0x78,0xcd,0x5a,0xf4,
0x1f,0xdd,0xa8,0x33,0x88,0x07,0xc7,0x31,0xb1,0x12,0x10,0x59,0x27,0x80,0xec,0x5f,
0x60,0x51,0x7f,0xa9,0x19,0xb5,0x4a,0x0d,0x2d,0xe5,0x7a,0x9f,0x93,0xc9,0x9c,0xef,
0xa0,0xe0,0x3b,0x4d,0xae,0x2a,0xf5,0xb0,0xc8,0xeb,0xbb,0x3c,0x83,0x53,0x99,0x61,
0x17,0x2b,0x04,0x7e,0xba,0x77,0xd6,0x26,0xe1,0x69,0x14,0x63,0x55,0x21,0x0c,0x7d};

static const u8 RCON[8] = {0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80};

#define XT(x) ((u8)(((x) << 1) ^ ((((x) >> 7) & 1) * 0x1b)))

static void aes_expand(const u8 *key, u8 *rk) /* rk: 240 bytes */
{
    int i;
    u8 t[4], k;
    memcpy(rk, key, 32);
    for (i = 8; i < 60; i++) {
        memcpy(t, rk + (i - 1) * 4, 4);
        if (i % 8 == 0) {
            k = t[0];
            t[0] = (u8)(SBOX[t[1]] ^ RCON[i / 8 - 1]);
            t[1] = SBOX[t[2]];
            t[2] = SBOX[t[3]];
            t[3] = SBOX[k];
        } else if (i % 8 == 4) {
            t[0] = SBOX[t[0]]; t[1] = SBOX[t[1]]; t[2] = SBOX[t[2]]; t[3] = SBOX[t[3]];
        }
        rk[i * 4 + 0] = rk[(i - 8) * 4 + 0] ^ t[0];
        rk[i * 4 + 1] = rk[(i - 8) * 4 + 1] ^ t[1];
        rk[i * 4 + 2] = rk[(i - 8) * 4 + 2] ^ t[2];
        rk[i * 4 + 3] = rk[(i - 8) * 4 + 3] ^ t[3];
    }
}

static void aes_encrypt_block(const u8 *rk, u8 *s)
{
    int r, c;
    u8 t[16], a0, a1, a2, a3;
    for (c = 0; c < 16; c++) s[c] ^= rk[c];
    for (r = 1; r <= 14; r++) {
        /* SubBytes + ShiftRows */
        for (c = 0; c < 4; c++) {
            t[c * 4 + 0] = SBOX[s[c * 4 + 0]];
            t[c * 4 + 1] = SBOX[s[((c + 1) % 4) * 4 + 1]];
            t[c * 4 + 2] = SBOX[s[((c + 2) % 4) * 4 + 2]];
            t[c * 4 + 3] = SBOX[s[((c + 3) % 4) * 4 + 3]];
        }
        if (r < 14) {
            for (c = 0; c < 4; c++) {   /* MixColumns */
                a0 = t[c * 4]; a1 = t[c * 4 + 1]; a2 = t[c * 4 + 2]; a3 = t[c * 4 + 3];
                s[c * 4 + 0] = (u8)(XT(a0) ^ XT(a1) ^ a1 ^ a2 ^ a3);
                s[c * 4 + 1] = (u8)(a0 ^ XT(a1) ^ XT(a2) ^ a2 ^ a3);
                s[c * 4 + 2] = (u8)(a0 ^ a1 ^ XT(a2) ^ XT(a3) ^ a3);
                s[c * 4 + 3] = (u8)(XT(a0) ^ a0 ^ a1 ^ a2 ^ XT(a3));
            }
        } else {
            memcpy(s, t, 16);
        }
        for (c = 0; c < 16; c++) s[c] ^= rk[r * 16 + c];
    }
}

static void aes_decrypt_block(const u8 *rk, u8 *s)
{
    int r, c;
    u8 t[16], a0, a1, a2, a3;
    for (c = 0; c < 16; c++) s[c] ^= rk[14 * 16 + c];
    for (r = 13; r >= 0; r--) {
        /* InvShiftRows + InvSubBytes */
        for (c = 0; c < 4; c++) {
            t[c * 4 + 0] = RSBOX[s[c * 4 + 0]];
            t[c * 4 + 1] = RSBOX[s[((c + 3) % 4) * 4 + 1]];
            t[c * 4 + 2] = RSBOX[s[((c + 2) % 4) * 4 + 2]];
            t[c * 4 + 3] = RSBOX[s[((c + 1) % 4) * 4 + 3]];
        }
        for (c = 0; c < 16; c++) t[c] ^= rk[r * 16 + c];
        if (r > 0) {
            for (c = 0; c < 4; c++) {   /* InvMixColumns = preprocessing + MixColumns */
                u8 u, v;
                a0 = t[c * 4]; a1 = t[c * 4 + 1]; a2 = t[c * 4 + 2]; a3 = t[c * 4 + 3];
                u = XT(a0 ^ a2); u = XT(u);
                v = XT(a1 ^ a3); v = XT(v);
                a0 ^= u; a1 ^= v; a2 ^= u; a3 ^= v;
                s[c * 4 + 0] = (u8)(XT(a0) ^ XT(a1) ^ a1 ^ a2 ^ a3);
                s[c * 4 + 1] = (u8)(a0 ^ XT(a1) ^ XT(a2) ^ a2 ^ a3);
                s[c * 4 + 2] = (u8)(a0 ^ a1 ^ XT(a2) ^ XT(a3) ^ a3);
                s[c * 4 + 3] = (u8)(XT(a0) ^ a0 ^ a1 ^ a2 ^ XT(a3));
            }
        } else {
            memcpy(s, t, 16);
        }
    }
}

/* IGE: c_i = E(p_i ^ c_{i-1}) ^ p_{i-1}; iv = c_0 (16 bytes) + p_0 (16 bytes) */
static void ige(const u8 *in, u8 *out, int n, const u8 *key, const u8 *iv, int decrypt)
{
    u8 rk[240], prev_x[16], prev_y[16], blk[16], cur[16];
    int i, j;
    aes_expand(key, rk);
    if (decrypt) {
        memcpy(prev_y, iv, 16);       /* previous ciphertext, mixed in after */
        memcpy(prev_x, iv + 16, 16);  /* previous plaintext, mixed in before */
    } else {
        memcpy(prev_x, iv, 16);       /* previous ciphertext, mixed in before */
        memcpy(prev_y, iv + 16, 16);  /* previous plaintext, mixed in after */
    }
    for (i = 0; i < n; i += 16) {
        memcpy(cur, in + i, 16);
        for (j = 0; j < 16; j++) blk[j] = cur[j] ^ prev_x[j];
        if (decrypt) aes_decrypt_block(rk, blk);
        else aes_encrypt_block(rk, blk);
        for (j = 0; j < 16; j++) blk[j] ^= prev_y[j];
        memcpy(out + i, blk, 16);
        memcpy(prev_x, blk, 16);
        memcpy(prev_y, cur, 16);
    }
}

/* ------------------------------------------------------------------ SHA-1 / SHA-256 */

#define ROL(x, n) (((x) << (n)) | ((x) >> (32 - (n))))
#define ROR(x, n) (((x) >> (n)) | ((x) << (32 - (n))))

static const u32 K256[64] = {
0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2};

static u32 be32(const u8 *p)
{
    return ((u32)p[0] << 24) | ((u32)p[1] << 16) | ((u32)p[2] << 8) | p[3];
}

static void put32(u8 *p, u32 v)
{
    p[0] = (u8)(v >> 24); p[1] = (u8)(v >> 16); p[2] = (u8)(v >> 8); p[3] = (u8)v;
}

static void sha256_block(u32 *h, const u8 *p)
{
    u32 w[64], a, b, c, d, e, f, g, hh, t1, t2;
    int i;
    for (i = 0; i < 16; i++) w[i] = be32(p + i * 4);
    for (i = 16; i < 64; i++)
        w[i] = w[i - 16] + (ROR(w[i - 15], 7) ^ ROR(w[i - 15], 18) ^ (w[i - 15] >> 3)) +
               w[i - 7] + (ROR(w[i - 2], 17) ^ ROR(w[i - 2], 19) ^ (w[i - 2] >> 10));
    a = h[0]; b = h[1]; c = h[2]; d = h[3]; e = h[4]; f = h[5]; g = h[6]; hh = h[7];
    for (i = 0; i < 64; i++) {
        t1 = hh + (ROR(e, 6) ^ ROR(e, 11) ^ ROR(e, 25)) + ((e & f) ^ (~e & g)) + K256[i] + w[i];
        t2 = (ROR(a, 2) ^ ROR(a, 13) ^ ROR(a, 22)) + ((a & b) ^ (a & c) ^ (b & c));
        hh = g; g = f; f = e; e = d + t1; d = c; c = b; b = a; a = t1 + t2;
    }
    h[0] += a; h[1] += b; h[2] += c; h[3] += d; h[4] += e; h[5] += f; h[6] += g; h[7] += hh;
}

static void sha1_block(u32 *h, const u8 *p)
{
    u32 w[80], a, b, c, d, e, t;
    int i;
    for (i = 0; i < 16; i++) w[i] = be32(p + i * 4);
    for (i = 16; i < 80; i++) w[i] = ROL(w[i - 3] ^ w[i - 8] ^ w[i - 14] ^ w[i - 16], 1);
    a = h[0]; b = h[1]; c = h[2]; d = h[3]; e = h[4];
    for (i = 0; i < 80; i++) {
        if (i < 20) t = ((b & c) | (~b & d)) + 0x5a827999;
        else if (i < 40) t = (b ^ c ^ d) + 0x6ed9eba1;
        else if (i < 60) t = ((b & c) | (b & d) | (c & d)) + 0x8f1bbcdc;
        else t = (b ^ c ^ d) + 0xca62c1d6;
        t += ROL(a, 5) + e + w[i];
        e = d; d = c; c = ROL(b, 30); b = a; a = t;
    }
    h[0] += a; h[1] += b; h[2] += c; h[3] += d; h[4] += e;
}

/* Merkle-Damgard over 64-byte blocks (SHA-1 and SHA-256) */
static void md32(void (*block)(u32 *, const u8 *), u32 *h, int nh,
                 const u8 *data, int len, u8 *out)
{
    u8 tail[128];
    int i, rest, tlen;
    u64 bits = (u64)len * 8;
    for (i = 0; i + 64 <= len; i += 64) block(h, data + i);
    rest = len - i;
    memcpy(tail, data + i, rest);
    tail[rest] = 0x80;
    tlen = (rest < 56) ? 64 : 128;
    memset(tail + rest + 1, 0, tlen - rest - 1);
    for (i = 0; i < 8; i++) tail[tlen - 1 - i] = (u8)(bits >> (8 * i));
    block(h, tail);
    if (tlen == 128) block(h, tail + 64);
    for (i = 0; i < nh; i++) put32(out + i * 4, h[i]);
}

static void sha256(const u8 *data, int len, u8 *out)
{
    u32 h[8] = {0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
                0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19};
    md32(sha256_block, h, 8, data, len, out);
}

static void sha1(const u8 *data, int len, u8 *out)
{
    u32 h[5] = {0x67452301, 0xefcdab89, 0x98badcfe, 0x10325476, 0xc3d2e1f0};
    md32(sha1_block, h, 5, data, len, out);
}

/* ------------------------------------------------------------------ SHA-512 / PBKDF2 */

#define ROR64(x, n) (((x) >> (n)) | ((x) << (64 - (n))))

static const u64 K512[80] = {
0x428a2f98d728ae22ULL,0x7137449123ef65cdULL,0xb5c0fbcfec4d3b2fULL,0xe9b5dba58189dbbcULL,
0x3956c25bf348b538ULL,0x59f111f1b605d019ULL,0x923f82a4af194f9bULL,0xab1c5ed5da6d8118ULL,
0xd807aa98a3030242ULL,0x12835b0145706fbeULL,0x243185be4ee4b28cULL,0x550c7dc3d5ffb4e2ULL,
0x72be5d74f27b896fULL,0x80deb1fe3b1696b1ULL,0x9bdc06a725c71235ULL,0xc19bf174cf692694ULL,
0xe49b69c19ef14ad2ULL,0xefbe4786384f25e3ULL,0x0fc19dc68b8cd5b5ULL,0x240ca1cc77ac9c65ULL,
0x2de92c6f592b0275ULL,0x4a7484aa6ea6e483ULL,0x5cb0a9dcbd41fbd4ULL,0x76f988da831153b5ULL,
0x983e5152ee66dfabULL,0xa831c66d2db43210ULL,0xb00327c898fb213fULL,0xbf597fc7beef0ee4ULL,
0xc6e00bf33da88fc2ULL,0xd5a79147930aa725ULL,0x06ca6351e003826fULL,0x142929670a0e6e70ULL,
0x27b70a8546d22ffcULL,0x2e1b21385c26c926ULL,0x4d2c6dfc5ac42aedULL,0x53380d139d95b3dfULL,
0x650a73548baf63deULL,0x766a0abb3c77b2a8ULL,0x81c2c92e47edaee6ULL,0x92722c851482353bULL,
0xa2bfe8a14cf10364ULL,0xa81a664bbc423001ULL,0xc24b8b70d0f89791ULL,0xc76c51a30654be30ULL,
0xd192e819d6ef5218ULL,0xd69906245565a910ULL,0xf40e35855771202aULL,0x106aa07032bbd1b8ULL,
0x19a4c116b8d2d0c8ULL,0x1e376c085141ab53ULL,0x2748774cdf8eeb99ULL,0x34b0bcb5e19b48a8ULL,
0x391c0cb3c5c95a63ULL,0x4ed8aa4ae3418acbULL,0x5b9cca4f7763e373ULL,0x682e6ff3d6b2b8a3ULL,
0x748f82ee5defb2fcULL,0x78a5636f43172f60ULL,0x84c87814a1f0ab72ULL,0x8cc702081a6439ecULL,
0x90befffa23631e28ULL,0xa4506cebde82bde9ULL,0xbef9a3f7b2c67915ULL,0xc67178f2e372532bULL,
0xca273eceea26619cULL,0xd186b8c721c0c207ULL,0xeada7dd6cde0eb1eULL,0xf57d4f7fee6ed178ULL,
0x06f067aa72176fbaULL,0x0a637dc5a2c898a6ULL,0x113f9804bef90daeULL,0x1b710b35131c471bULL,
0x28db77f523047d84ULL,0x32caab7b40c72493ULL,0x3c9ebe0a15c9bebcULL,0x431d67c49c100d4cULL,
0x4cc5d4becb3e42b6ULL,0x597f299cfc657e2aULL,0x5fcb6fab3ad6faecULL,0x6c44198c4a475817ULL};

static const u64 H512[8] = {
0x6a09e667f3bcc908ULL,0xbb67ae8584caa73bULL,0x3c6ef372fe94f82bULL,0xa54ff53a5f1d36f1ULL,
0x510e527fade682d1ULL,0x9b05688c2b3e6c1fULL,0x1f83d9abfb41bd6bULL,0x5be0cd19137e2179ULL};

static u64 be64(const u8 *p)
{
    return ((u64)be32(p) << 32) | be32(p + 4);
}

static void sha512_block(u64 *h, const u8 *p)
{
    u64 w[80], a, b, c, d, e, f, g, hh, t1, t2;
    int i;
    for (i = 0; i < 16; i++) w[i] = be64(p + i * 8);
    for (i = 16; i < 80; i++)
        w[i] = w[i - 16] + (ROR64(w[i - 15], 1) ^ ROR64(w[i - 15], 8) ^ (w[i - 15] >> 7)) +
               w[i - 7] + (ROR64(w[i - 2], 19) ^ ROR64(w[i - 2], 61) ^ (w[i - 2] >> 6));
    a = h[0]; b = h[1]; c = h[2]; d = h[3]; e = h[4]; f = h[5]; g = h[6]; hh = h[7];
    for (i = 0; i < 80; i++) {
        t1 = hh + (ROR64(e, 14) ^ ROR64(e, 18) ^ ROR64(e, 41)) + ((e & f) ^ (~e & g)) +
             K512[i] + w[i];
        t2 = (ROR64(a, 28) ^ ROR64(a, 34) ^ ROR64(a, 39)) + ((a & b) ^ (a & c) ^ (b & c));
        hh = g; g = f; f = e; e = d + t1; d = c; c = b; b = a; a = t1 + t2;
    }
    h[0] += a; h[1] += b; h[2] += c; h[3] += d; h[4] += e; h[5] += f; h[6] += g; h[7] += hh;
}

static void put64(u8 *p, u64 v)
{
    put32(p, (u32)(v >> 32));
    put32(p + 4, (u32)v);
}

/* SHA-512 of (128-byte block already absorbed into state) + msg (< 112 bytes) */
static void sha512_finish(const u64 *state, const u8 *msg, int mlen, u8 *out)
{
    u64 h[8];
    u8 blk[128];
    int i;
    u64 bits = (u64)(128 + mlen) * 8;
    memcpy(h, state, sizeof(h));
    memcpy(blk, msg, mlen);
    blk[mlen] = 0x80;
    memset(blk + mlen + 1, 0, 128 - mlen - 1);
    put64(blk + 120, bits);
    sha512_block(h, blk);
    for (i = 0; i < 8; i++) put64(out + i * 8, h[i]);
}

static void pbkdf2_sha512(const u8 *pw, int pwlen, const u8 *salt, int saltlen,
                          int iters, u8 *out)
{
    u8 key[128], pad[128], u[64], msg[112];
    u64 ist[8], ost[8];
    int i, j;
    memset(key, 0, 128);
    if (pwlen > 128) {           /* hash long keys first */
        u64 h[8];
        int k;
        u8 tail[256];
        memcpy(h, H512, sizeof(h));
        for (k = 0; k + 128 <= pwlen; k += 128) sha512_block(h, pw + k);
        i = pwlen - k;
        memcpy(tail, pw + k, i);
        tail[i] = 0x80;
        j = (i < 112) ? 128 : 256;
        memset(tail + i + 1, 0, j - i - 1);
        put64(tail + j - 8, (u64)pwlen * 8);
        sha512_block(h, tail);
        if (j == 256) sha512_block(h, tail + 128);
        for (k = 0; k < 8; k++) put64(key + k * 8, h[k]);
    } else {
        memcpy(key, pw, pwlen);
    }
    for (i = 0; i < 128; i++) pad[i] = key[i] ^ 0x36;
    memcpy(ist, H512, sizeof(ist));
    sha512_block(ist, pad);
    for (i = 0; i < 128; i++) pad[i] = key[i] ^ 0x5c;
    memcpy(ost, H512, sizeof(ost));
    sha512_block(ost, pad);
    /* U1 = HMAC(salt || INT(1)); salt is short (Telegram: 40 bytes) */
    if (saltlen > 104) saltlen = 104;
    memcpy(msg, salt, saltlen);
    msg[saltlen] = 0; msg[saltlen + 1] = 0; msg[saltlen + 2] = 0; msg[saltlen + 3] = 1;
    sha512_finish(ist, msg, saltlen + 4, u);
    sha512_finish(ost, u, 64, u);
    memcpy(out, u, 64);
    for (i = 1; i < iters; i++) {
        sha512_finish(ist, u, 64, u);
        sha512_finish(ost, u, 64, u);
        for (j = 0; j < 64; j++) out[j] ^= u[j];
    }
}

/* ------------------------------------------------------------------ Python glue */

static PyObject *py_ige(PyObject *args, int decrypt)
{
    const char *data, *key, *iv;
    int n, kn, ivn;
    PyObject *res;
    if (!PyArg_ParseTuple(args, "s#s#s#", &data, &n, &key, &kn, &iv, &ivn))
        return NULL;
    if (kn != 32 || ivn != 32 || n % 16) {
        PyErr_SetString(PyExc_ValueError, "IGE needs a 32-byte key and iv, data in 16s");
        return NULL;
    }
    res = PyString_FromStringAndSize(NULL, n);
    if (res == NULL)
        return NULL;
    ige((const u8 *)data, (u8 *)PyString_AS_STRING(res), n, (const u8 *)key,
        (const u8 *)iv, decrypt);
    return res;
}

static PyObject *tg_ige_encrypt(PyObject *self, PyObject *args)
{
    return py_ige(args, 0);
}

static PyObject *tg_ige_decrypt(PyObject *self, PyObject *args)
{
    return py_ige(args, 1);
}

static PyObject *tg_sha256(PyObject *self, PyObject *args)
{
    const char *data;
    int n;
    u8 out[32];
    if (!PyArg_ParseTuple(args, "s#", &data, &n))
        return NULL;
    sha256((const u8 *)data, n, out);
    return PyString_FromStringAndSize((const char *)out, 32);
}

static PyObject *tg_sha1(PyObject *self, PyObject *args)
{
    const char *data;
    int n;
    u8 out[20];
    if (!PyArg_ParseTuple(args, "s#", &data, &n))
        return NULL;
    sha1((const u8 *)data, n, out);
    return PyString_FromStringAndSize((const char *)out, 20);
}

static PyObject *tg_pbkdf2_sha512(PyObject *self, PyObject *args)
{
    const char *pw, *salt;
    int pn, sn, iters;
    u8 out[64];
    if (!PyArg_ParseTuple(args, "s#s#i", &pw, &pn, &salt, &sn, &iters))
        return NULL;
    if (iters < 1 || sn > 104) {
        PyErr_SetString(PyExc_ValueError, "bad pbkdf2 arguments");
        return NULL;
    }
    pbkdf2_sha512((const u8 *)pw, pn, (const u8 *)salt, sn, iters, out);
    return PyString_FromStringAndSize((const char *)out, 64);
}

static const PyMethodDef tg_methods[] = {
    {"ige_encrypt", (PyCFunction)tg_ige_encrypt, METH_VARARGS, NULL},
    {"ige_decrypt", (PyCFunction)tg_ige_decrypt, METH_VARARGS, NULL},
    {"sha256", (PyCFunction)tg_sha256, METH_VARARGS, NULL},
    {"sha1", (PyCFunction)tg_sha1, METH_VARARGS, NULL},
    {"pbkdf2_sha512", (PyCFunction)tg_pbkdf2_sha512, METH_VARARGS, NULL},
    {NULL, NULL, 0, NULL}
};

#ifdef __SYMBIAN32__
#define TG_EXPORT DL_EXPORT(void)   /* EXPORT_C: Python looks it up as ordinal 1 */
#else
#define TG_EXPORT void
#endif

TG_EXPORT inittgnative(void)
{
    Py_InitModule("tgnative", (PyMethodDef *)tg_methods);
}
