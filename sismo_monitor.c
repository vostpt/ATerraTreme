/*
 * sismo_monitor.c
 *
 * Compile:
 *   gcc -O2 -o sismo_monitor sismo_monitor.c -lcurl -lcjson
 *
 */

#define _GNU_SOURCE

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <time.h>
#include <curl/curl.h>
#include <cjson/cJSON.h>

#define MAX_SENT          5000
#define POLL_INTERVAL     45
#define HASH_SIZE         8192
#define MAX_ID_LEN        64

/* ---------- Hash set de IDs já enviados ---------- */
typedef struct Node {
    char id[MAX_ID_LEN];
    struct Node *next;
} Node;

Node *hash_table[HASH_SIZE] = {0};
int   sent_count = 0;

unsigned int hash(const char *str) {
    unsigned int h = 5381;
    int c;
    while ((c = *str++))
        h = ((h << 5) + h) + c;
    return h % HASH_SIZE;
}

int already_sent(const char *id) {
    unsigned int h = hash(id);
    Node *n = hash_table[h];
    while (n) {
        if (strcmp(n->id, id) == 0)
            return 1;
        n = n->next;
    }
    return 0;
}

void mark_sent(const char *id) {
    if (already_sent(id)) return;

    if (sent_count >= MAX_SENT) {
        int bucket = rand() % HASH_SIZE;
        Node *n = hash_table[bucket];
        while (n) {
            Node *tmp = n;
            n = n->next;
            free(tmp);
            sent_count--;
        }
        hash_table[bucket] = NULL;
    }

    unsigned int h = hash(id);
    Node *node = malloc(sizeof(Node));
    if (!node) return;

    strncpy(node->id, id, MAX_ID_LEN - 1);
    node->id[MAX_ID_LEN - 1] = '\0';
    node->next = hash_table[h];
    hash_table[h] = node;
    sent_count++;
}

/* ---------- libcurl memory buffer ---------- */
struct MemoryStruct {
    char *memory;
    size_t size;
};

static size_t WriteMemoryCallback(void *contents, size_t size, size_t nmemb, void *userp) {
    size_t realsize = size * nmemb;
    struct MemoryStruct *mem = (struct MemoryStruct *)userp;

    char *ptr = realloc(mem->memory, mem->size + realsize + 1);
    if (!ptr) return 0;

    mem->memory = ptr;
    memcpy(&(mem->memory[mem->size]), contents, realsize);
    mem->size += realsize;
    mem->memory[mem->size] = 0;
    return realsize;
}

char *fetch_url(const char *url) {
    CURL *curl = curl_easy_init();
    if (!curl) return NULL;

    struct MemoryStruct chunk = {0};
    chunk.memory = malloc(1);
    chunk.size = 0;

    curl_easy_setopt(curl, CURLOPT_URL, url);
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, WriteMemoryCallback);
    curl_easy_setopt(curl, CURLOPT_WRITEDATA, (void *)&chunk);
    curl_easy_setopt(curl, CURLOPT_USERAGENT, "SismoBot-C/3.1");
    curl_easy_setopt(curl, CURLOPT_TIMEOUT, 20L);
    curl_easy_setopt(curl, CURLOPT_FOLLOWLOCATION, 1L);

    CURLcode res = curl_easy_perform(curl);
    curl_easy_cleanup(curl);

    if (res != CURLE_OK) {
        free(chunk.memory);
        return NULL;
    }
    return chunk.memory;
}

/* ---------- Processar um novo sismo ---------- */
void process_new_quake(cJSON *quake) {
    cJSON *time_item = cJSON_GetObjectItem(quake, "time");
    if (!time_item || !cJSON_IsString(time_item)) {
        fprintf(stderr, "Sismo sem campo 'time' válido\n");
        return;
    }
    const char *time_str = time_item->valuestring;

    // Região
    const char *region = "Portugal";
    cJSON *reg = cJSON_GetObjectItem(quake, "obsRegion");
    if (reg && cJSON_IsString(reg) && reg->valuestring[0] != '\0') {
        region = reg->valuestring;
    }

    // Magnitude
    double magnitude = 0.0;
    cJSON *mag = cJSON_GetObjectItem(quake, "magnitud");
    if (mag) {
        if (cJSON_IsString(mag))
            magnitude = atof(mag->valuestring);
        else if (cJSON_IsNumber(mag))
            magnitude = mag->valuedouble;
        if (magnitude < 0.0) magnitude = 0.0;
    }

    // Latitude
    double lat = 0.0;
    cJSON *latj = cJSON_GetObjectItem(quake, "lat");
    if (!latj) latj = cJSON_GetObjectItem(quake, "latitude");
    if (latj) {
        if (cJSON_IsString(latj))
            lat = atof(latj->valuestring);
        else if (cJSON_IsNumber(latj))
            lat = latj->valuedouble;
    }

    // Longitude
    double lon = 0.0;
    cJSON *lonj = cJSON_GetObjectItem(quake, "lon");
    if (!lonj) lonj = cJSON_GetObjectItem(quake, "longitude");
    if (lonj) {
        if (cJSON_IsString(lonj))
            lon = atof(lonj->valuestring);
        else if (cJSON_IsNumber(lonj))
            lon = lonj->valuedouble;
    }

    // === Formatar data a partir do time do sismo ===
    // Formato IPMA: "2026-07-22T05:20:47"
    char date_str[64] = "Sem data";
    struct tm tm = {0};

    if (strptime(time_str, "%Y-%m-%dT%H:%M:%S", &tm) != NULL) {
        strftime(date_str, sizeof(date_str), "%d-%m-%Y pelas %H:%M (hora local)", &tm);
    } else {
        snprintf(date_str, sizeof(date_str), "%s", time_str);
    }

    // === Criar ficheiro JSON temporário ===
    char tmpfile[128];
    snprintf(tmpfile, sizeof(tmpfile), "/tmp/sismo_%ld_%d.json",
             (long)time(NULL), rand() % 10000);

    FILE *f = fopen(tmpfile, "w");
    if (!f) {
        fprintf(stderr, "Erro ao criar ficheiro temporário %s\n", tmpfile);
        return;
    }

    // Escapar " e \ na região
    char region_escaped[256];
    int j = 0;
    for (int i = 0; region[i] && j < 250; i++) {
        if (region[i] == '"' || region[i] == '\\')
            region_escaped[j++] = '\\';
        region_escaped[j++] = region[i];
    }
    region_escaped[j] = '\0';

    fprintf(f,
        "{\n"
        "  \"id\": \"%s\",\n"
        "  \"location\": \"%s\",\n"
        "  \"scale\": %.1f,\n"
        "  \"date\": \"%s\",\n"
        "  \"intensity\": \"Sem info a esta hora\",\n"
        "  \"latitude\": %.6f,\n"
        "  \"longitude\": %.6f\n"
        "}\n",
        time_str,
        region_escaped,
        magnitude,
        date_str,
        lat,
        lon
    );
    fclose(f);

    // === Chamar o helper Python ===
    char cmd[512];
    snprintf(cmd, sizeof(cmd), "python3 process_quake.py \"%s\"", tmpfile);

    printf("→ Novo sismo: %s  M%.1f  lat=%.4f lon=%.4f\n"
           "   time=%s → %s\n",
           region, magnitude, lat, lon, time_str, date_str);

    int ret = system(cmd);

    if (ret == 0) {
        mark_sent(time_str);
        printf("✓ Processado e marcado como enviado\n\n");
    } else {
        printf("✗ Falha no process_quake.py (código %d)\n\n", ret);
    }
}

/* ---------- Loop principal de monitorização ---------- */
void monitor_loop(void) {
    const char *urls[] = {
        "https://api.ipma.pt/open-data/observation/seismic/7.json",
        "https://api.ipma.pt/open-data/observation/seismic/3.json"
    };

    printf("C Monitor iniciado (intervalo = %d segundos)\n", POLL_INTERVAL);

    while (1) {
        for (int u = 0; u < 2; u++) {
            char *json_str = fetch_url(urls[u]);
            if (!json_str) {
                fprintf(stderr, "Falha ao obter %s\n", urls[u]);
                continue;
            }

            cJSON *root = cJSON_Parse(json_str);
            free(json_str);
            if (!root) continue;

            cJSON *data = cJSON_GetObjectItem(root, "data");
            if (!cJSON_IsArray(data)) {
                cJSON_Delete(root);
                continue;
            }

            cJSON *quake;
            cJSON_ArrayForEach(quake, data) {
                cJSON *time_item = cJSON_GetObjectItem(quake, "time");
                if (!time_item || !cJSON_IsString(time_item))
                    continue;

                const char *id = time_item->valuestring;
                if (already_sent(id))
                    continue;

                process_new_quake(quake);
                usleep(1500000);   // 1.5 segundos entre notificações
            }

            cJSON_Delete(root);
        }

        sleep(POLL_INTERVAL);
    }
}

int main(void) {
    curl_global_init(CURL_GLOBAL_DEFAULT);
    srand((unsigned int)time(NULL));

    monitor_loop();

    curl_global_cleanup();
    return 0;
}