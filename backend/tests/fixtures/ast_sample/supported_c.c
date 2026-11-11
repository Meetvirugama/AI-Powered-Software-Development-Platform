#include <stdio.h>
#include <stdlib.h>
#include "local_header.h"

#define BUFFER_CAPACITY 1024

struct PacketHeader {
    int version;
    int payload_length;
};

int validate_header(const struct PacketHeader *hdr) {
    if (hdr == NULL) {
        return 0;
    }
    return hdr->payload_length >= 0 && hdr->payload_length <= BUFFER_CAPACITY;
}

int process_packet(const struct PacketHeader *hdr) {
    if (!validate_header(hdr)) {
        return -1;
    }
    return hdr->version;
}
