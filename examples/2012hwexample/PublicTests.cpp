#include <iostream>
#include <string>

#include "PartnerMatcher.h"
using namespace std;

// Feel free to use these courses and students for your own test cases
Course comp1021("Introduction to Computer Science", "COMP 1021", 3);
Course comp1022p("Introduction to Computing with Java", "COMP 1022P", 3);
Course comp1023("Introduction to Python Programming", "COMP 1023", 3);
Course comp1028("Extended Python Programming Bridging Course", "COMP 1028", 1);
Course comp1029c("C Programming Bridging Course", "COMP 1029C", 1);
Course comp2011("Programming with C++", "COMP 2011", 4);
Course comp2012("Object-Oriented Programming and Data Structures", "COMP 2012", 4);
Course comp2012h("Honors Object-Oriented Programming and Data Structures", "COMP 2012H", 5);
Course comp3021("Java Programming", "COMP 3021", 3);
Course comp3031("Principles of Programming Languages", "COMP 3031", 3);
Course comp4021("Internet Computing", "COMP 4021", 3);

int sid = 1;
Student tmchan("CHAN, Tai Man", sid++, 1, LOCAL, KOWLOON, SENG);
Student whding("DING, Wan Hang", sid++, 1, LOCAL, HONG_KONG_ISLAND, SSCI);
Student jdoe("DOE, John", sid++, 2, INTERNATIONAL, CAMPUS, SSCI);
Student sli("LI, Si", sid++, 4, MAINLAND, OTHERS, SSCI);

void test1() {
    cout << "Testing Course::addOffering, Course::hasOffering and Course::getOffering." << endl;
    comp2012.printOfferings();
    CourseOffering *offering = comp2012.addOffering(Fall, 2024);
    if (!offering) {
        cout << "Course::addOffering failed." << endl;
        return;
    }

    if (!comp2012.hasOffering(Fall, 2024)) {
        cout << "Course::hasOffering failed." << endl;
        return;
    }

    if (offering != comp2012.getOffering(Fall, 2024)) {
        cout << "Course::getOffering failed." << endl;
        return;
    }
    offering = comp2012.getOffering(Fall, 2025);
    if (offering) {
        cout << "Course::getOffering failed." << endl;
        return;
    }
    comp2012.printOfferings();
    cout << endl;
}

void test2() {
    cout << "Testing Course::addOffering and Course::hasOffering." << endl;
    comp2012.printOfferings();
    CourseOffering *offering = comp2012.addOffering(Fall, 2024);
    if (!offering) {
        cout << "Course::addOffering failed." << endl;
        return;
    }

    if (!comp2012.hasOffering(Fall, 2024)) {
        cout << "Course::hasOffering failed." << endl;
        return;
    }
    comp2012.addOffering(Spring, 2024);
    if (!comp2012.hasOffering(Fall, 2024)) {
        cout << "Course::addOffering or Course::hasOffering failed." << endl;
        return;
    }

    comp2012.printOfferings();
    cout << endl;
}

void test3() {
    cout << "Testing Course::addOffering." << endl;
    comp2012.printOfferings();
    comp2012.addOffering(Fall, 2024);
    comp2012.addOffering(Winter, 2025);
    comp2012.addOffering(Spring, 2025);
    comp2012.printOfferings();
    cout << endl;
}

void test4() {
    cout << "Testing Course::compareTo." << endl;
    if (comp1021.compareTo(comp2012) >= 0 || comp1021.compareTo(comp1021) || comp2012.compareTo(comp1021) <= 0) {
        cout << "Course::compareTo failed." << endl;
    }
    cout << endl;
}

void test5() {
    cout << "Testing CourseOffering::assignGrade." << endl;
    CourseOffering *off = comp2012.addOffering(Fall, 2024);
    comp2012.printOfferings();
    // Students are not enrolled into the courses, but this can be ignored to test CourseOffering
    off->assignGrade(tmchan.getId(), A_MINUS);
    if (off->getGrade(tmchan.getId()) != gradeToOrdinal(A_MINUS)) {
        cout << "CourseOffering::assignGrade failed." << endl;
    }
    cout << endl;
}

void test6() {
    cout << "Testing CourseOffering::assignGrade." << endl;
    CourseOffering *off1 = comp2012.addOffering(Fall, 2024);
    comp2012.printOfferings();
    // Students are not enrolled into the courses, but this can be ignored to test CourseOffering
    off1->assignGrade(tmchan.getId(), A_MINUS);
    off1->assignGrade(whding.getId(), B_MINUS);
    if (off1->getGrade(tmchan.getId()) != gradeToOrdinal(A_MINUS) || off1->getGrade(whding.getId()) != gradeToOrdinal(B_MINUS)) {
        cout << "CourseOffering::assignGrade failed." << endl;
        return;
    }
    CourseOffering *off2 = comp2012.addOffering(Spring, 2025);
    comp2012.printOfferings();
    off2->assignGrade(jdoe.getId(), A);
    if (off1->getGrade(jdoe.getId()) != gradeToOrdinal(A)) {
        cout << "CourseOffering::assignGrade failed." << endl;
    }
    comp2012.printOfferings();
    cout << endl;
}

void test7() {
    cout << "Testing CourseOffering::compareTo." << endl;
    CourseOffering *off1 = comp2012.addOffering(Fall, 2024);
    CourseOffering *off2 = comp2012.addOffering(Spring, 2025);
    CourseOffering *off3 = comp1021.addOffering(Spring, 2025);
    if (off1->compareTo(*off2) >= 0 || off2->compareTo(*off2) || off2->compareTo(*off1) <= 0 || off1->compareTo(*off3) <= 0) {
        cout << "CourseOffering::compareTo failed." << endl;
        return;
    }

    cout << "Testing CourseOffering::sameCourse." << endl;
    if (!off1->sameCourse(*off2) || off2->sameCourse(*off3)) {
        cout << "CourseOffering::sameCourse failed." << endl;
        return;
    }

    cout << "Testing CourseOffering::sameSemester." << endl;
    if (!off1->sameSemester(Fall, 2024) || off2->sameSemester(Fall, 2025)) {
        cout << "CourseOffering::sameSemester failed." << endl;
    }
    cout << endl;
}

void test8() {
    cout << "Testing Student::enrollCourse." << endl;
    tmchan.enrollCourse(comp2011, Spring, 2025, C_PLUS)
        .enrollCourse(comp2012, Fall, 2025, ONGOING);
    tmchan.printCourseHistory();
    cout << endl;
}

void test9() {
    cout << "Testing Student::enrollCourse." << endl;
    tmchan.enrollCourse(comp2011, Spring, 2025, C_PLUS)
        .enrollCourse(comp2012, Fall, 2025, ONGOING);
    tmchan.printInfo();
    tmchan.printCourseHistory();

    whding.enrollCourse(comp2011, Spring, 2025, C_PLUS)
        .enrollCourse(comp2012, Fall, 2025, ONGOING);
    whding.printInfo();
    whding.printCourseHistory();

    jdoe.enrollCourse(comp2011, Fall, 2024, C_PLUS)
        .enrollCourse(comp2012, Spring, 2025, ONGOING);
    jdoe.printInfo();
    jdoe.printCourseHistory();

    cout << "Scores:\n";
    cout << "Score between tmchan & jdoe: " << tmchan.calculateScore(jdoe) << endl;
    cout << "Score between jdoe & tmchan: " << jdoe.calculateScore(tmchan) << endl;
    cout << "Score between whding & jdoe: " << whding.calculateScore(jdoe) << endl;
    cout << "Score between jdoe & whding: " << jdoe.calculateScore(whding) << endl;
    cout << "Score between tmchan & whding: " << tmchan.calculateScore(whding) << endl;
    cout << "Score between whding & tmchan: " << whding.calculateScore(tmchan) << endl;
}

void test10() {
    cout << "Testing PartnerMatcher::addStudent." << endl;
    PartnerMatcher matcher(Fall, 2024);
    matcher.addStudent(tmchan).addStudent(whding);

    matcher.printStudents();
    cout << endl;
}

void test11() {
    cout << "Testing PartnerMatcher::addCourse and PartnerMatcher::updateMappings." << endl;
    PartnerMatcher matcher(Fall, 2024);
    matcher.addStudent(tmchan).addStudent(whding);
    matcher.addCourse(comp2011).addCourse(comp2012);
    tmchan.enrollCourse(comp2011, Fall, 2023, A).enrollCourse(comp2012, Fall, 2024, A_PLUS);
    whding.enrollCourse(comp2011, Spring, 2024, B).enrollCourse(comp2012, Fall, 2024, B_PLUS);

    matcher.updateMappings();
    matcher.printAllMappings();
    cout << endl;
}

void test12() {
    cout << "Testing PartnerMatcher::updateMappings and PartnerMatcher::matchStudents." << endl;
    PartnerMatcher matcher(Fall, 2024);
    matcher.addStudent(tmchan).addStudent(whding);
    matcher.addCourse(comp2011).addCourse(comp2012);
    tmchan.enrollCourse(comp2011, Fall, 2023, A).enrollCourse(comp2012, Fall, 2024, A_PLUS);
    whding.enrollCourse(comp2011, Spring, 2024, B).enrollCourse(comp2012, Fall, 2024, B_PLUS);

    matcher.updateMappings();
    matcher.matchStudents(MOST_SIMILAR);
    matcher.printStudents();
    cout << endl;
}

void test13() {
    cout << "Testing PartnerMatcher::updateMappings and PartnerMatcher::matchStudents." << endl;
    PartnerMatcher matcher(Fall, 2024);
    matcher.addStudent(tmchan).addStudent(whding).addStudent(jdoe).addStudent(sli);
    matcher.addCourse(comp2011).addCourse(comp2012);
    tmchan.enrollCourse(comp2011, Fall, 2023, A).enrollCourse(comp2012, Fall, 2024, A_PLUS);
    whding.enrollCourse(comp2011, Spring, 2024, B).enrollCourse(comp2012, Fall, 2024, B_PLUS);
    jdoe.enrollCourse(comp2011, Fall, 2023, A).enrollCourse(comp2012, Spring, 2024, A_PLUS);
    sli.enrollCourse(comp2011, Fall, 2022, A).enrollCourse(comp2012, Spring, 2023, A_PLUS);

    matcher.updateMappings();
    cout << "--- MOST SIMILAR ---" << endl;
    matcher.matchStudents(MOST_SIMILAR);
    matcher.printStudents();

    cout << "--- LEAST SIMILAR ---" << endl;
    matcher.matchStudents(LEAST_SIMILAR);
    matcher.printStudents();
    cout << endl;
}

void test14() {
    cout << "Testing PartnerMatcher::matchStudents." << endl;
    PartnerMatcher matcher(Fall, 2024);
    matcher.addStudent(tmchan).addStudent(whding).addStudent(jdoe).addStudent(sli);
    matcher.addCourse(comp2011).addCourse(comp2012).addCourse(comp3021);
    tmchan.enrollCourse(comp2011, Fall, 2023, A).enrollCourse(comp2012, Fall, 2024, A_PLUS);
    whding.enrollCourse(comp2011, Spring, 2024, B).enrollCourse(comp2012, Fall, 2024, B_PLUS);
    jdoe.enrollCourse(comp2011, Fall, 2023, A).enrollCourse(comp2012, Spring, 2024, A_PLUS);
    sli.enrollCourse(comp2011, Fall, 2022, A).enrollCourse(comp2012, Spring, 2023, A_PLUS);

    matcher.updateMappings();
    matcher.matchStudents(MOST_SIMILAR);
    matcher.printAllMappings();

    cout << "--- Updating Enrollment and Mappings ---" << endl;
    whding.enrollCourse(comp3021, Spring, 2025, ONGOING);
    jdoe.enrollCourse(comp3021, Spring, 2025, ONGOING);

    matcher.updateMappings();
    matcher.printAllMappings();

    cout << "--- Matching ---" << endl;
    matcher.matchStudents(MOST_SIMILAR);
    matcher.printStudents();
    cout << endl;
}

void test15() {
    cout << "Testing PartnerMatcher::moveToNextSemester." << endl;
    PartnerMatcher matcher(Spring, 2025);
    matcher.addStudent(tmchan).addStudent(whding).addStudent(jdoe).addStudent(sli);
    matcher.addCourse(comp2011).addCourse(comp2012).addCourse(comp3021);
    tmchan.enrollCourse(comp2011, Fall, 2023, A).enrollCourse(comp2012, Fall, 2024, A_PLUS);
    whding.enrollCourse(comp2011, Spring, 2024, B).enrollCourse(comp2012, Fall, 2024, B_PLUS);
    jdoe.enrollCourse(comp2011, Fall, 2023, A).enrollCourse(comp2012, Spring, 2024, A_PLUS);
    sli.enrollCourse(comp2011, Fall, 2022, A).enrollCourse(comp2012, Spring, 2023, A_PLUS);

    matcher.updateMappings();
    matcher.printStudents();
    matcher.printAllMappings();

    cout << "--- Moving to next semester ---" << endl;
    PartnerMatcher &matcher2 = matcher.moveToNextSemester();
    cout << "New semester is " << semesterToString(matcher2.getSemester()) << " " << matcher2.getYear() << "." << endl;
    matcher2.printStudents();
    matcher2.printAllMappings();
    cout << endl;

    delete &matcher2;
}


int main() {
    const int num_test = 15;
    void(*funcs[])() = {test1, test2, test3, test4, test5, test6, test7, test8, test9, test10, test11, test12, test13, test14, test15};

    int test;
    cout << "Enter the test number (1 - " << num_test << "): ";
    cin >> test;
    if (test <= 0 || test > num_test) {
        cout << "Invalid test number. Exiting.\n";
        return 0;
    }
    funcs[test - 1]();
}

