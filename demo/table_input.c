#include <stdio.h>
int main(void) {
    for (int r = 1; r <= 3; r++) {
        for (int c = 1; c <= 3; c++) {
            printf("%dx%d=%d ", r, c, r * c);
        }
        printf("\n");
    }
    return 0;
}
