/* assert.h for the FFmpeg sources in h264dec (found before the system one): a failed assertion
 * inside the decoder does not abort the process; h264dec_fail() jumps back to h264dec_decode(),
 * which resets the decoder and returns H264DEC_ERR_FATAL. Re-includable like the real one. */
#ifndef H264DEC_CATCH_ASSERT_H
#define H264DEC_CATCH_ASSERT_H
void h264dec_fail(const char *file, int line, const char *what);
#endif
#undef assert
#ifdef NDEBUG
#define assert(e) ((void)0)
#else
#define assert(e) ((e) ? (void)0 : h264dec_fail(__FILE__, __LINE__, #e))
#endif
