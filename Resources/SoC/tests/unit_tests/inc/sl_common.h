#ifndef SL_COMMON_H
#define SL_COMMON_H

#if defined(__GNUC__)
/** @brief A GCC style macro for handling packed structures. */
#define SL_ATTRIBUTE_PACKED __attribute__((packed))

/** @brief A macro for handling packed structures.
 *  @n Use this macro before the structure definition.
 *  @n X denotes the maximum alignment of structure members. X is not supported with
 *  GCC. GCC always uses 1 byte maximum alignment.
 */
#define SL_PACK_START(x)

/** @brief A macro for handling packed structures.
 *  @n Use this macro after the structure definition.
 *  @n With GCC, add SL_ATTRIBUTE_PACKED after the closing curly braces of the structure
 *  definition.
 */
#define SL_PACK_END()

/** @brief GCC style macro for aligning a variable. */
#define SL_ATTRIBUTE_ALIGN(X) __attribute__((aligned(X)))

/** @brief A macro for aligning a variable.
 *  @n Use this macro before the variable definition.
 *  @n X denotes the storage alignment value in bytes.
 *  @n To be GCC-compatible, use SL_ATTRIBUTE_ALIGN(X) before the semicolon on normal
 *  variables. Use SL_ATTRIBUTE_ALIGN(X) before the opening curly brace on structure variables.
 */
#define SL_ALIGN(X)

#define SL_WEAK __attribute__((weak))

#elif defined(_MSC_VER)
/** @brief A GCC style macro for handling packed structures. */
#define SL_ATTRIBUTE_PACKED

/** @brief A macro for handling packed structures.
 *  @n Use this macro before the structure definition.
 *  @n X denotes the maximum alignment of structure members. X is not supported with
 *  GCC. GCC always uses 1 byte maximum alignment.
 */
#define SL_PACK_START(x)

/** @brief A macro for handling packed structures.
 *  @n Use this macro after the structure definition.
 *  @n With GCC, add SL_ATTRIBUTE_PACKED after the closing curly braces of the structure
 *  definition.
 */
#define SL_PACK_END()

/** @brief GCC style macro for aligning a variable. */
#define SL_ATTRIBUTE_ALIGN(X)

/** @brief A macro for aligning a variable.
 *  @n Use this macro before the variable definition.
 *  @n X denotes the storage alignment value in bytes.
 *  @n To be GCC-compatible, use SL_ATTRIBUTE_ALIGN(X) before the semicolon on normal
 *  variables. Use SL_ATTRIBUTE_ALIGN(X) before the opening curly brace on structure variables.
 */
#define SL_ALIGN(X)

#define SL_WEAK
#else
#endif

#endif // SL_COMMON_H