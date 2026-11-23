/*
 * h264dec_compat.c: libc pieces that Symbian estlib lacks and FFmpeg uses
 * (vsnprintf, snprintf, tempnam). Empty on other platforms.
 */
#ifdef __SYMBIAN32__
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>

/* Bounded printf: each conversion is formatted on its own by estlib's sprintf into a small
 * local buffer (width/precision capped), %s is copied directly. */
int vsnprintf(char *out, size_t size, const char *fmt, va_list ap)
{
    size_t n = 0;
    char spec[24], tmp[160];
    const char *p = fmt;
#define PUT(c) do { if (n + 1 < size) out[n] = (c); n++; } while (0)
    while (*p) {
        const char *s0;
        int k, lng = 0, prec = -1, width = 0;
        char conv;
        if (*p != '%') { PUT(*p); p++; continue; }
        s0 = p++;
        if (*p == '%') { PUT('%'); p++; continue; }
        while (*p == '-' || *p == '+' || *p == ' ' || *p == '#' || *p == '0') p++;
        if (*p == '*') { width = va_arg(ap, int); p++; }
        else while (*p >= '0' && *p <= '9') { width = width * 10 + (*p - '0'); p++; }
        if (*p == '.') {
            p++; prec = 0;
            if (*p == '*') { prec = va_arg(ap, int); p++; }
            else while (*p >= '0' && *p <= '9') { prec = prec * 10 + (*p - '0'); p++; }
        }
        while (*p == 'h' || *p == 'l' || *p == 'z' || *p == 'j' || *p == 't' || *p == 'L') {
            if (*p == 'l') lng++;
            p++;
        }
        conv = *p;
        if (!conv) break;
        p++;
        if (width > 100) width = 100;
        if (width < -100) width = -100;
        if (prec > 100 && conv != 's') prec = 100;
        /* rebuild the spec with explicit numbers instead of '*' */
        k = 0;
        spec[k++] = '%';
        {
            const char *f = s0 + 1;
            while (*f == '-' || *f == '+' || *f == ' ' || *f == '#' || *f == '0') {
                if (k < 8) spec[k++] = *f;
                f++;
            }
        }
        if (conv == 's') {
            const char *str = va_arg(ap, const char *);
            int len, pad, left = (memchr(spec, '-', k) != NULL);
            if (str == NULL) str = "(null)";
            len = (int)strlen(str);
            if (prec >= 0 && len > prec) len = prec;
            if (width < 0) { left = 1; width = -width; }
            pad = width > len ? width - len : 0;
            if (!left) while (pad-- > 0) PUT(' ');
            for (k = 0; k < len; k++) PUT(str[k]);
            if (left) while (pad-- > 0) PUT(' ');
            continue;
        }
        k += sprintf(spec + k, "%d", width < 0 ? -width : width);
        if (width < 0 && k < 20) { memmove(spec + 2, spec + 1, k); spec[1] = '-'; k++; }
        if (prec >= 0) k += sprintf(spec + k, ".%d", prec);
        switch (conv) {
        case 'd': case 'i': case 'u': case 'x': case 'X': case 'o':
            if (lng >= 2) {
                spec[k++] = 'l'; spec[k++] = 'l'; spec[k++] = conv; spec[k] = 0;
                sprintf(tmp, spec, va_arg(ap, long long));
            } else {
                if (lng == 1) {
                    spec[k++] = 'l'; spec[k++] = conv; spec[k] = 0;
                    sprintf(tmp, spec, va_arg(ap, long));
                } else {
                    spec[k++] = conv; spec[k] = 0;
                    sprintf(tmp, spec, va_arg(ap, int));
                }
            }
            break;
        case 'c':
            spec[k++] = 'c'; spec[k] = 0;
            sprintf(tmp, spec, va_arg(ap, int));
            break;
        case 'p':
            sprintf(tmp, "%p", va_arg(ap, void *));
            break;
        case 'f': case 'F': case 'e': case 'E': case 'g': case 'G':
            spec[k++] = conv; spec[k] = 0;
            {
                double v = va_arg(ap, double);
                if (v > 1e30 || v < -1e30) strcpy(tmp, v > 0 ? "huge" : "-huge");
                else sprintf(tmp, spec, v);
            }
            break;
        default:
            tmp[0] = '?'; tmp[1] = 0;
            break;
        }
        for (k = 0; tmp[k]; k++) PUT(tmp[k]);
    }
    if (size > 0) out[n < size ? n : size - 1] = 0;
#undef PUT
    return (int)n;
}

int snprintf(char *out, size_t size, const char *fmt, ...)
{
    va_list ap;
    int r;
    va_start(ap, fmt);
    r = vsnprintf(out, size, fmt, ap);
    va_end(ap);
    return r;
}

/* only used by av_tempfile() (two-pass encoding), never by the decoder */
char *tempnam(const char *dir, const char *pfx)
{
    (void)dir; (void)pfx;
    return NULL;
}
#endif
