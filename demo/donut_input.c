#include <stdio.h>
int main(void) {
    int total = 0;
    for (int i = 1; i <= 6; i++) {
        total += i * i;
        printf("row %d -> %d\n", i, i * i);
    }
    printf("total = %d\n", total);
    return 0;
}
