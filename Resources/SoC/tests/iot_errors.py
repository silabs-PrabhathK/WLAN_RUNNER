from enum import IntEnum


class IOTStatus(IntEnum):
    IOT_SOCKET_ERROR         = -1  # Unspecified error
    IOT_SOCKET_ESOCK         = -2  # Invalid socket
    IOT_SOCKET_EINVAL        = -3  # Invalid argument
    IOT_SOCKET_ENOTSUP       = -4  # Operation not supported
    IOT_SOCKET_ENOMEM        = -5  # Not enough memory
    IOT_SOCKET_EAGAIN        = -6  # Operation would block or timed out
    IOT_SOCKET_EINPROGRESS   = -7  # Operation in progress
    IOT_SOCKET_ETIMEDOUT     = -8  # Operation timed out
    IOT_SOCKET_EISCONN       = -9  # Socket is connected
    IOT_SOCKET_ENOTCONN      = -10  # Socket is not connected
    IOT_SOCKET_ECONNREFUSED  = -11  # Connection rejected by the peer
    IOT_SOCKET_ECONNRESET    = -12  # Connection reset by the peer
    IOT_SOCKET_ECONNABORTED  = -13  # Connection aborted locally
    IOT_SOCKET_EALREADY      = -14  # Connection already in progress
    IOT_SOCKET_EADDRINUSE    = -15  # Address in use
    IOT_SOCKET_EHOSTNOTFOUND = -16  # Host not found