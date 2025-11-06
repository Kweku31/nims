#include<stdio.h>
#include<math.h>

#define FN(x) ((x*x*x)-x-1)
#define DV(x) (3*x*x -1)
#define FN1(x) ((x*x*x)+(2*x*x)+x-1)
#define DV1(x) (3*x*x +4*x+1)

int main(){
int z;
printf("Input 001 for Finding the root for x^3 - x -1\n");
printf("Input 002 for Finding the root for x^3 + 2x^2 + x - 1\n");
printf("Input 003 for the matrix multiplication\n");
printf("Please input your choice :\n");
scanf("%d",&z);

if(z==001){
int v;
printf("Finding the root for x^3 - x -1\n");
printf("Input 1 for Bisection Method\n");
printf("Input 2 for Newton-Raphson Method\n");
printf("Input 3 for Secant Method\n");
printf("Please input your choice :\n");
scanf("%d",&v);

if(v==1){
float a=1;
float b=3;
float c;
        while(fabs(b-a)>=0.000001){
        if(FN(a)==0)
        {
        printf("The root of the function is %f\n",a);
        break;
        }
        else if(FN(b)==0) 
        {
        printf("The root of the function is %f\n",b);
        break;
        }
        else if(FN(a)*FN(b)>0){
        printf("The func(a) and func(b) must have different signs or check your a and b");
        break;
        }
      if(c =(a+b)/2){
        if(FN(c)==0)
        {
        printf("The root of the function is %f\n",c);
        break;
        }
        else if (FN(a)*FN(c)>0){
        a = c;
        }
        else if (FN(b)*FN(c)>0){
        b = c; 
        }
        }
        }
        printf("The root of the function is %f\n",c);
}
if(v==2){
float c;
float p=1;
float q;
        while(fabs(FN(q))>=0.000001){
        q = p - (FN(p)/DV(p));
        p = q;
        if(DV(p) == 0){
        printf("Error!!,Method fails\n");
        break;
        } 
        }
        printf("The root of the function is %f\n",q);
} 
if(v==3){
float a=1;
float b=3;
float u;
        while(fabs(FN(u))>=0.000001){
        u = a -((b-a)/(FN(b)-FN(a)))*FN(a);
        a=b;
        b=u;
        if(FN(b)==FN(a)){
        printf("Error!!,Method fails\n");
        break;
        }
        }
        printf("The root of the function is %f\n",u);

}
}
if(z==002){
int v;
printf("Finding the root for x^3 + 2x^2 + x - 1\n");
printf("Input 1 for Bisection Method\n");
printf("Input 2 for Newton-Raphson Method\n");
printf("Input 3 for Secant Method\n");
printf("Please input your choice :\n");
scanf("%d",&v);

if(v==1){
float a=-1;
float b=2;
float c;
        while(fabs(b-a)>=0.000001){
        if(FN1(a)==0)
        {
        printf("The root of the function is %f\n",a);
        break;
        }
        else if(FN1(b)==0) 
        {
        printf("The root of the function is %f\n",b);
        break;
        }
        else if(FN1(a)*FN1(b)>0){
        printf("The func(a) and func(b) must have different signs or check your a and b");
        break;
        }
       if(c =(a+b)/2){
        if(FN1(c)==0)
        {
        printf("The root of the function is %f\n",c);
        break;
        }
        else if (FN1(a)*FN1(c)>0){
        a = c;
        }
        else if (FN1(b)*FN1(c)>0){
        b = c; 
        }
        }
        }
        printf("The root of the function is %f\n",c);
}
if(v==2){
float c;
float p=1;
float q;
        while(fabs(FN1(q))>=0.000001){
        q = p - (FN1(p)/DV1(p));
        p = q;
        if(DV1(p) == 0){
        printf("Error!!,Method fails\n");
        break;
        } 
        }
        printf("The root of the function is %f\n",q);
} 
if(v==3){
float a=-1;
float b=2;
float u;
        while(fabs(FN1(u))>=0.000001){
        u = a -((b-a)/(FN1(b)-FN1(a)))*FN1(a);
        a=b;
        b=u;
        if(FN1(b)==FN1(a)){
        printf("Error!!,Method fails\n");
        break;
        }
        }
        printf("The root of the function is %f\n",u);

}
}
 
if(z==003){
    int f,o,h, c[4][1];

    int a[4][5] = {
        {1, 2, 3, 4, 5},
        {6, 7, 8, 9, 10},
        {11, 12, 13, 14, 15},
        {16, 17, 18, 19, 20},


    };

    int b[5][1] = {
        {1},
        {2},
        {3},
        {4},
        {5},

    };
  for ( f = 0; f < 4; f++)
  {
      for ( o = 0; o < 1; o++)
      {
          c[f][o] = 0;
         for (h  = 0; h < 5; h++)
            {
                c[f][o] += a[f][h] * b[h][o];
            }
        }
    }
   printf("The product of the two matrices is = \n");
    for ( f = 0; f < 4; f++)
    {
        for ( o = 0; o < 1; o++)
        {
            printf("%d", c[f][o]);
        }
        printf("\n");
    }
}         
}

